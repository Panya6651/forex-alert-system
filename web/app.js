// ตรวจสอบและระบุที่อยู่ของ Backend API (ให้สลับใช้ localhost ถ้าเทสในเครื่อง)
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:8000'
  : 'https://forex-alert-system-production.up.railway.app'; // จะถูกแทนที่ด้วย url จริงบน Render ภายหลัง

let deferredPrompt;
const btnNotify = document.getElementById('btn-notify');
const btnInstall = document.getElementById('btn-install');
const notifyStatus = document.getElementById('notify-status');
const signalContainer = document.getElementById('signal-container');

// ── 1. ระบบดึงสัญญาณมาแสดงผล (Poll สัญญาณทุกๆ 10 วินาที) ──
async function fetchSignals() {
  try {
    const res = await fetch(`${API_BASE}/api/signals`);
    if (!res.ok) throw new Error('API Error');
    const signals = await res.json();
    
    if (signals.length === 0) {
      signalContainer.innerHTML = '<div class="empty-state">ยังไม่มีสัญญาณวิเคราะห์ในช่วงนี้</div>';
      return;
    }

    signalContainer.innerHTML = signals.map(sig => {
      const isBuy = sig.direction.toUpperCase() === 'BUY';
      const cardClass = isBuy ? 'buy' : 'sell';
      const timeString = new Date(sig.timestamp).toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' });
      const dateString = new Date(sig.timestamp).toLocaleDateString('th-TH', { day: 'numeric', month: 'short' });
      
      return `
        <div class="signal-card ${cardClass}">
          <div class="card-header">
            <span class="symbol">${sig.symbol}</span>
            <span class="direction">${sig.direction}</span>
          </div>
          <div class="card-body">
            <div class="confidence">ความเชื่อมั่นของเทรนด์: ${(sig.confidence * 100).toFixed(1)}%</div>
            <div class="reasons">${sig.reasons}</div>
          </div>
          <span class="timestamp">${dateString} ${timeString}</span>
        </div>
      `;
    }).join('');
  } catch (e) {
    console.error('ดึงสัญญาณราคาล้มเหลว:', e);
    signalContainer.innerHTML = '<div class="empty-state" style="color: var(--accent-red)">เชื่อมต่อเซิร์ฟเวอร์ไม่ได้...</div>';
  }
}

// ── 2. ระบบลงทะเบียน Push Notification ──
// แปลง VAPID Key ที่เป็น base64 ให้เป็น Uint8Array เพื่อเรียก API ของเบราว์เซอร์
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding)
    .replace(/\-/g, '+')
    .replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

async function configurePushSubscription() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    notifyStatus.innerText = '⚠️ เบราว์เซอร์หรืออุปกรณ์นี้ไม่รองรับการแจ้งเตือน Push Notification';
    btnNotify.classList.add('disabled');
    return;
  }

  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    
    if (sub) {
      notifyStatus.innerText = '🔔 เปิดการแจ้งเตือนแล้ว! ระบบจะแจ้งเตือนเมื่อพบจุด BUY/SELL';
      btnNotify.innerText = '✅ พร้อมรับสัญญาณแล้ว';
      btnNotify.classList.add('disabled');
      return;
    }

    // ดึง Public Key จาก API หลังบ้าน
    const res = await fetch(`${API_BASE}/api/vapid-key`);
    const { publicKey } = await res.json();
    
    btnNotify.addEventListener('click', async () => {
      try {
        const option = {
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(publicKey)
        };
        const newSub = await reg.pushManager.subscribe(option);
        
        // บันทึก subscription กลับไปที่ DB หลังบ้าน
        const subData = JSON.parse(JSON.stringify(newSub));
        const saveRes = await fetch(`${API_BASE}/api/subscribe`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(subData)
        });

        if (saveRes.ok) {
          notifyStatus.innerText = '🔔 สมัครรับแจ้งเตือนจุดซื้อขายสำเร็จ!';
          btnNotify.innerText = '✅ พร้อมรับสัญญาณแล้ว';
          btnNotify.classList.add('disabled');
        } else {
          throw new Error('บันทึกสิทธิ์ไม่สำเร็จ');
        }
      } catch (err) {
        console.error('สมัครแจ้งเตือนล้มเหลว:', err);
        notifyStatus.innerText = '❌ สมัครรับแจ้งเตือนล้มเหลว กรุณาอนุญาตสิทธิ์ในอุปกรณ์ของคุณ';
      }
    });

  } catch (e) {
    console.error('ตรวจสอบสิทธิ์ล้มเหลว:', e);
  }
}

// ── 3. จัดการการติดตั้งแบบ PWA App ──
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
  btnInstall.style.display = 'inline-block';
});

btnInstall.addEventListener('click', async () => {
  if (deferredPrompt) {
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === 'accepted') {
      btnInstall.style.display = 'none';
    }
    deferredPrompt = null;
  }
});

// เริ่มทำงานเมื่อเปิดหน้าเว็บ
window.addEventListener('DOMContentLoaded', () => {
  // ลงทะเบียน Service Worker
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js')
      .then(() => {
        console.log('Service Worker Registered');
        configurePushSubscription();
      });
  }

  fetchSignals();
  setInterval(fetchSignals, 10000);
});
