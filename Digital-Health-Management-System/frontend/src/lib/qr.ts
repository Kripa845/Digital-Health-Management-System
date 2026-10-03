// Health card QR helpers shared by the patient card and the admin QR dialog.
// The QR always encodes <frontend URL>/public-profile/<uuid_token>, never the
// patient ID: the token can be reissued if a card is lost, the ID cannot.

/**
 * The public frontend address printed in QR codes (VITE_FRONTEND_URL), so a card
 * printed from localhost or an admin's own host still opens the real site.
 * Falls back to the current origin only when the variable is not set.
 */
export function frontendBaseUrl(): string {
  const configured = (import.meta.env.VITE_FRONTEND_URL as string | undefined)?.trim().replace(/\/+$/, '')
  if (configured) return configured
  if (import.meta.env.PROD) {
    console.warn('VITE_FRONTEND_URL is not set; QR codes use the current address instead.')
  }
  return window.location.origin
}

export function publicProfileUrl(uuidToken: string): string {
  return `${frontendBaseUrl()}/public-profile/${uuidToken}`
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!))
}

export type PrintableCard = {
  fullName: string
  patientId: string
  bloodGroup?: string | null
  emergencyContact?: string | null
}

/** Open a print window with the wallet card, reusing the QR already drawn on the page (by element id). */
export function printHealthCard(qrElementId: string, card: PrintableCard) {
  const svg = document.getElementById(qrElementId)
  const qrMarkup = svg ? new XMLSerializer().serializeToString(svg) : ''
  const w = window.open('', 'print', 'width=520,height=720')
  if (!w) return
  const fullName = escapeHtml(card.fullName)
  const patientId = escapeHtml(card.patientId)
  w.document.write(`<!doctype html><html><head><title>Health Card — ${patientId}</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif;color:#0f172a;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px}
  .card{width:340px;border:2px solid #0d9488;border-radius:20px;padding:26px;text-align:center}
  .brand{font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:#0d9488}
  .name{font-size:20px;font-weight:800;margin-top:4px}
  .qr{margin:18px auto;width:180px;height:180px;padding:10px;border:1px solid #e2e8f0;border-radius:14px}
  .qr svg{width:100%;height:100%}
  .rows{text-align:left;margin-top:14px;border-top:1px solid #e2e8f0;padding-top:14px}
  .row{display:flex;justify-content:space-between;font-size:13px;padding:4px 0}
  .lbl{color:#64748b;text-transform:uppercase;font-size:10px;letter-spacing:.08em;font-weight:700}
  .val{font-weight:700;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
  .foot{margin-top:14px;font-size:10px;color:#64748b}
</style></head><body onload="window.print();setTimeout(function(){window.close()},300)">
  <div class="card">
    <div class="brand">Mero Care Card</div>
    <div class="name">${fullName}</div>
    <div class="qr">${qrMarkup}</div>
    <div class="rows">
      <div class="row"><span class="lbl">Patient ID</span><span class="val">${patientId}</span></div>
      <div class="row"><span class="lbl">Blood group</span><span class="val">${escapeHtml(card.bloodGroup ?? '—')}</span></div>
      <div class="row"><span class="lbl">Emergency</span><span class="val">${escapeHtml(card.emergencyContact ?? '—')}</span></div>
    </div>
    <div class="foot">Scan reveals identity essentials only — never private records.</div>
  </div>
</body></html>`)
  w.document.close()
}
