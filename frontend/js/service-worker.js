/* Finlumiq service worker - Phase 1
 * Phase 1 supports registration and local test notifications.
 * The push event listener is ready for the server push subscription added in Phase 2.
 */

const SW_VERSION = 'Finlumiq-pwa-v1';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// Phase 2 will send real push messages from Flask through the Web Push service.
self.addEventListener('push', (event) => {
  let payload = {
    title: 'Finlumiq',
    body: 'You have a new update.',
    url: './dashboard.html',
    tag: 'Finlumiq-general'
  };

  if (event.data) {
    try {
      const incoming = event.data.json();
      payload = { ...payload, ...incoming };
    } catch (error) {
      payload.body = event.data.text() || payload.body;
    }
  }

  const notificationOptions = {
    body: String(payload.body || 'You have a new update.'),
    icon: './icons/icon-192.png',
    badge: './icons/icon-192.png',
    tag: String(payload.tag || 'Finlumiq-general'),
    renotify: false,
    data: { url: String(payload.url || './dashboard.html') }
  };

  event.waitUntil(
    self.registration.showNotification(
      String(payload.title || 'Finlumiq'),
      notificationOptions
    )
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const requestedUrl = event.notification.data && event.notification.data.url
    ? event.notification.data.url
    : './dashboard.html';

  event.waitUntil((async () => {
    const target = new URL(requestedUrl, self.registration.scope);

    // Only allow notification clicks to navigate within this Finlumiq origin.
    if (target.origin !== self.location.origin) {
      return;
    }

    const windows = await self.clients.matchAll({
      type: 'window',
      includeUncontrolled: true
    });

    for (const client of windows) {
      if ('focus' in client) {
        await client.navigate(target.href);
        return client.focus();
      }
    }

    if (self.clients.openWindow) {
      return self.clients.openWindow(target.href);
    }
  })());
});
