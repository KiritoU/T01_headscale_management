/**
 * Copy text to clipboard. Works on HTTP (LAN IP) via execCommand fallback —
 * navigator.clipboard requires a secure context (HTTPS or localhost).
 */
export async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // Fall through to legacy copy on permission / policy errors.
    }
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.left = '-9999px'
  textarea.style.top = '0'
  document.body.appendChild(textarea)
  textarea.select()
  textarea.setSelectionRange(0, text.length)

  try {
    const copied = document.execCommand('copy')
    if (!copied) {
      throw new Error('Copy command was rejected by the browser')
    }
  } finally {
    document.body.removeChild(textarea)
  }
}
