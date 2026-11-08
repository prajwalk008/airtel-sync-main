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
3. Describe a business problem and monthly budget to see a sample catalogue-based suggestion.
4. Browse eight service categories, including broadband, leased line, SIMs, messaging, cloud, security, CCTV and POS.
5. Preview an illustrative combined monthly bill and view three order-status scenarios.

Login and recommendations are local demonstrations. No OTP, payment, actual AI call, callback, purchase, or subscription change occurs. The order screens currently use sample data; connecting them to `GET /v1/orders/:id/tracker` in the local Tracker API is the next integration step. Exact catalogue pricing, eligibility and availability remain the main service's responsibility.
