import QRCode from 'react-qr-code'
import { publicProfileUrl } from '@/lib/qr'

/**
 * The one QR generator in the app (react-qr-code). Encodes the public profile
 * link for the card's uuid_token. `id` lets printHealthCard copy the drawing.
 */
export function HealthCardQr({
  id, uuidToken, size = 256, className,
}: {
  id: string
  uuidToken: string
  size?: number
  className?: string
}) {
  const link = publicProfileUrl(uuidToken)
  return (
    <QRCode
      id={id}
      value={link}
      size={size}
      level="M"
      className={className}
      data-link={link}
      title={`QR code for ${link}`}
      style={{ height: '100%', width: '100%' }}
    />
  )
}
