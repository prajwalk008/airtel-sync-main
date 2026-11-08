import csv
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / 'backend/config/policy.json').read_text())

def money(value):
    return float(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

class Catalogue:
    def __init__(self, directory=None):
        directory = Path(directory or ROOT / 'data/source')
        with (directory / 'product_catalogue.csv').open(encoding='utf-8-sig', newline='') as f:
            self.products = {}
            for row in csv.DictReader(f):
                for key in ['price_min_inr_per_month', 'price_max_inr_per_month', 'one_time_setup_inr', 'min_contract_months', 'min_employees', 'min_sites', 'typical_install_days']:
                    row[key] = int(row[key])
                self.products[row['product_id']] = row
        self.registries = {}
        with (directory / 'smb_leads.csv').open(encoding='utf-8-sig', newline='') as f:
            self.leads = list(csv.DictReader(f))
        for kind, key in [('gstin', 'gstin'), ('udyam', 'udyam_number')]:
            with (directory / f'mock_{kind}_registry.csv').open(encoding='utf-8-sig', newline='') as f:
                self.registries[kind] = {r[key]: r for r in csv.DictReader(f)}

    def gst_active(self, profile):
        return self.registries['gstin'].get(profile.get('gstin', ''), {}).get('status', '').lower() == 'active'

    def reasons(self, product, profile):
        reasons = []
        tier = profile.get('cityTier')
        if not tier or str(tier) not in product['available_city_tiers'].split(';'): reasons.append('City tier is unconfirmed or unavailable')
        if profile.get('employees', 1) < product['min_employees']: reasons.append('Employee eligibility not met')
        if profile.get('sites', 1) < product['min_sites']: reasons.append('Site eligibility not met')
        if product['requires_gstin'] == 'Y' and not self.gst_active(profile): reasons.append('Active mock GSTIN required')
        if product['product_id'] in {'P01','P02','P03'} and not profile.get('fibreAvailable', False): reasons.append('Fibre availability not confirmed')
        return reasons

    def price(self, items, profile):
        if not items: raise HTTPException(422, 'Select at least one product')
        if len({x['productId'] for x in items}) != len(items): raise HTTPException(422, 'Duplicate products')
        ids = {x['productId'] for x in items}
        lines = []
        for item in items:
            p = self.products.get(item['productId'])
            if not p: raise HTTPException(422, 'Unknown catalogue product')
            errors = self.reasons(p, profile)
            dependencies = p['requires_one_of'].split('|') if p['requires_one_of'] else []
            if dependencies and not ids.intersection(dependencies): errors.append('Requires one of: ' + ', '.join(dependencies))
            if errors: raise HTTPException(422, {'productId': p['product_id'], 'reasons': errors})
            q = item['quantity']
            if type(q) is not int or not 1 <= q <= 1000: raise HTTPException(422, 'Quantity must be 1–1000')
            lines.append({'productId': p['product_id'], 'name': p['product_name'], 'unit': p['unit'], 'quantity': q, 'unitPrice': p['price_min_inr_per_month'], 'monthlyExTax': p['price_min_inr_per_month'] * q, 'setupExTax': p['one_time_setup_inr'] * q, 'contractMonths': p['min_contract_months'], 'installDays': p['typical_install_days']})
        subtotal = sum(x['monthlyExTax'] for x in lines)
        setup = sum(x['setupExTax'] for x in lines)
        tax = money(Decimal(subtotal) * Decimal(POLICY['gst_rate']))
        setup_tax = money(Decimal(setup) * Decimal(POLICY['gst_rate']))
        return {'items': lines, 'monthlyExTax': subtotal, 'monthlyGst': tax, 'monthlyTotal': money(subtotal + tax), 'setupExTax': setup, 'setupGst': setup_tax, 'setupTotal': money(setup + setup_tax), 'payToday': money(subtotal + tax + setup + setup_tax), 'gstRate': POLICY['gst_rate'], 'contractMonths': max(x['contractMonths'] for x in lines), 'installDays': max(x['installDays'] for x in lines), 'pricePolicy': POLICY['price_policy']}

    def recommend(self, profile):
        needs = profile.get('needs') or POLICY['segments'].get(profile.get('segment', 'micro'), POLICY['segments']['micro'])['needs']
        quantities = {'P16': profile.get('employees', 1), 'P20': profile.get('employees', 1), 'P07': profile.get('employees', 1)}
        selected = {}; gaps = []
        def add(pid, need):
            p = self.products[pid]
            reasons = self.reasons(p, profile)
            if reasons: gaps.append({'need': need, 'reason': '; '.join(reasons)}); return
            deps = p['requires_one_of'].split('|') if p['requires_one_of'] else []
            if deps and not set(selected).intersection(deps):
                available = [d for d in deps if not self.reasons(self.products[d], profile)]
                if not available: gaps.append({'need': need, 'reason': 'No eligible dependency'}); return
                add(available[0], 'Required connection')
            selected[pid] = {'productId': pid, 'quantity': quantities.get(pid, profile.get('sites', 1) if p['unit'] == 'per site' else 1)}
        for need in needs:
            pid = POLICY['need_products'].get(need)
            if not pid: gaps.append({'need': need, 'reason': 'No matching catalogue service'}); continue
            if pid == 'P01' and not profile.get('fibreAvailable'): pid = 'P04'
            add(pid, need)
        if not selected: return {'bundles': [], 'gaps': gaps, 'manualReview': True}
        result = []
        recommended = self.price(list(selected.values()), profile)
        for name, items in [('Recommended', list(selected.values())), ('Essential', [next(iter(selected.values()))])]:
            if name == 'Essential' and len(selected) == 1: continue
            quote = self.price(items, profile)
            result.append({'name': name, **quote, 'withinBudget': quote['monthlyTotal'] <= profile.get('budget', 0), 'gaps': gaps if name == 'Recommended' else gaps + [{'need': 'Other stated needs', 'reason': 'Essential option contains only the first eligible service'}]})
        if 'P07' not in selected and not self.reasons(self.products['P07'], profile):
            expanded = self.price([*selected.values(), {'productId': 'P07', 'quantity': 1}], profile)
            result.append({'name': 'With mobile', **expanded, 'withinBudget': expanded['monthlyTotal'] <= profile.get('budget', 0), 'gaps': gaps})
        return {'bundles': result, 'gaps': gaps, 'manualReview': False, 'budgetGap': max(0, money(recommended['monthlyTotal'] - profile.get('budget', 0))), 'serviceability': 'Demo city-tier and declared fibre check; no live address lookup'}
