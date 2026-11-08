# Accel Business frontend prototype

Two local frontends demonstrate the Project Udyam Digital customer journey. The design uses the supplied Airtel website and app screenshots for visual direction, while using the case study's fictional Accel Business name.

## Desktop website

```powershell
cd X:\codes\projects2\airtel_sync\web
npm install
npm run dev
```

Open the local URL printed by Vite. The responsive layout also works on narrow screens.

## React Native Android app

```powershell
cd X:\codes\projects2\airtel_sync\mobile
npm install
npm run android
```

Expo starts a development server and opens an Android emulator if one is installed. You can also run `npm start` and scan the Expo QR code on a compatible Android device. This is source and an Expo development build, not a packaged APK.

## Prototype journey

1. Enter a 10-digit mobile number to sign in, or create an account with a name and business name.
2. Use the home shortcuts for AI partner, human help, catalogue and management.
3. Open **Speak with AI business partner**, describe a business problem and monthly budget, allow business-answer processing, and start the backend conversation. Answer the returned questions by typing or selecting an option. Confirm interpreted answers and receive catalogue-priced bundles inside the original chat panel.
4. Browse eight service categories, including broadband, leased line, SIMs, messaging, cloud, security, CCTV and POS.
5. Preview an illustrative combined monthly bill and view three order-status scenarios.

Visual login remains a local demo; the advisor creates a matching authenticated demo backend session when you start a conversation. The shared backend owns recommendations and pricing. Real LLM interpretation and personalised explanations use `OPENAI_API_KEY` and `OPENAI_MODEL` in `backend/.env`, with optional customer AI consent; without credentials, the backend uses its deterministic fallback. No model key is included in either frontend. Callback, subscription management and the existing order-screen examples remain illustrative.

## Start the advisor backend

From the repository root run `npm run dev:stack`, then run the website or Expo as above. Use the original website URL `/` and its **AI business partner** navigation item. The separate `/journey` interface was removed.

The website proxies `/api` to port 8000. Expo Go uses the development computer's host on port 8000. The development stack listens on the LAN so a phone on the same Wi-Fi can connect. For an override, put `EXPO_PUBLIC_API_URL=http://YOUR_COMPUTER_LAN_IP:8000` in `mobile/.env`, or use a deployed HTTPS backend URL, and reload Expo Go. Do not use `127.0.0.1` as the backend URL on a physical phone. Restart Metro after the new shared-module configuration if it was already running.
