/* Finlumiq PWA / notification helper - Phase 1.
 * No backend subscription or VAPID key is used in this phase.
 */
(function () {
  'use strict';

  const scriptUrl = document.currentScript && document.currentScript.src
    ? document.currentScript.src
    : new URL('./js/push-notifications.js', document.baseURI).href;
  const frontendBase = new URL('../', scriptUrl);
  const serviceWorkerUrl = new URL('service-worker.js', frontendBase);
  const manifestUrl = new URL('manifest.webmanifest', frontendBase);
  const iconUrl = new URL('icons/icon-192.png', frontendBase);

  let registrationPromise = null;

  function getSupport() {
    return {
      secure: window.isSecureContext === true,
      notifications: 'Notification' in window,
      serviceWorker: 'serviceWorker' in navigator
    };
  }

  async function registerServiceWorker() {
    const support = getSupport();

    if (!support.secure) {
      throw new Error('Notifications require HTTPS or localhost/127.0.0.1. Open Finlumiq through a secure URL.');
    }
    if (!support.serviceWorker) {
      throw new Error('This browser does not support service workers. Please use an updated Chrome browser.');
    }

    if (!registrationPromise) {
      const scope = new URL('./', frontendBase).pathname;
      registrationPromise = navigator.serviceWorker.register(serviceWorkerUrl.href, { scope })
        .then(() => navigator.serviceWorker.ready)
        .catch((error) => {
          registrationPromise = null;
          throw error;
        });
    }

    return registrationPromise;
  }

  async function requestPermissionAndTest() {
    const support = getSupport();

    if (!support.notifications) {
      throw new Error('Notifications are not supported by this browser. Try Chrome on Android.');
    }
    if (!support.secure) {
      throw new Error('A secure HTTPS URL is required on your Android phone.');
    }

    // Must be invoked directly from a user click so the browser can display permission UI.
    let permission = Notification.permission;
    if (permission === 'default') {
      permission = await Notification.requestPermission();
    }

    if (permission !== 'granted') {
      if (permission === 'denied') {
        throw new Error('Notifications are blocked for this site. Open Chrome site settings, allow Notifications, and try again.');
      }
      throw new Error('Notification permission was not granted. Please try again.');
    }

    const registration = await registerServiceWorker();
    await registration.showNotification('Finlumiq notifications enabled', {
      body: 'Your phone is ready to show Finlumiq notifications. Real fee and budget alerts will be connected in Phase 2.',
      icon: iconUrl.href,
      badge: iconUrl.href,
      tag: 'Finlumiq-phase1-test',
      renotify: false,
      data: { url: new URL('dashboard.html', frontendBase).href },
      vibrate: [150, 80, 150]
    });

    return { permission, registration };
  }

  async function sendTestNotification() {
    if (!('Notification' in window) || Notification.permission !== 'granted') {
      throw new Error('Enable notifications first.');
    }

    const registration = await registerServiceWorker();
    await registration.showNotification('Finlumiq test notification', {
      body: 'This is a test from your Finlumiq app.',
      icon: iconUrl.href,
      badge: iconUrl.href,
      tag: 'Finlumiq-phase1-test',
      renotify: false,
      data: { url: new URL('dashboard.html', frontendBase).href },
      vibrate: [150, 80, 150]
    });
  }

  function getStatus() {
    const support = getSupport();
    return {
      secure: support.secure,
      notificationSupported: support.notifications,
      serviceWorkerSupported: support.serviceWorker,
      permission: support.notifications ? Notification.permission : 'unsupported'
    };
  }

  window.FinlumiqPush = {
    registerServiceWorker,
    requestPermissionAndTest,
    sendTestNotification,
    getStatus,
    manifestUrl: manifestUrl.href
  };

  // Register the service worker when this script is included. Permission is never requested here.
  window.addEventListener('load', () => {
    registerServiceWorker().catch((error) => {
      console.warn('[Finlumiq PWA] Service worker registration:', error.message);
    });
  }, { once: true });
})();
