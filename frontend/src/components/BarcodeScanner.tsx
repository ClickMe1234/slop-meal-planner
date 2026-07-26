import type { IScannerControls } from '@zxing/browser'
import { Camera, ImageUp } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button } from './ui'

async function createBarcodeReader() {
  const [{ BrowserMultiFormatReader }, { DecodeHintType }] = await Promise.all([
    import('@zxing/browser'),
    import('@zxing/library'),
  ])
  return new BrowserMultiFormatReader(new Map([[DecodeHintType.TRY_HARDER, true]]))
}

export function BarcodeScanner({ onCode, compact = false }: { onCode: (code: string) => void; compact?: boolean }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const controlsRef = useRef<IScannerControls | null>(null)
  const [active, setActive] = useState(false)
  const [error, setError] = useState('')
  const cameraAvailable = typeof window !== 'undefined' && window.isSecureContext && Boolean(navigator.mediaDevices?.getUserMedia)

  const stop = () => {
    controlsRef.current?.stop()
    controlsRef.current = null
    setActive(false)
  }
  useEffect(() => stop, [])

  const start = async () => {
    if (!cameraAvailable || !videoRef.current) return
    setError('')
    setActive(true)
    try {
      const reader = await createBarcodeReader()
      controlsRef.current = await reader.decodeFromVideoDevice(undefined, videoRef.current, (result, _error, controls) => {
        if (!result) return
        onCode(result.getText())
        controls.stop()
        controlsRef.current = null
        setActive(false)
      })
    } catch (reason) {
      setActive(false)
      setError(reason instanceof Error ? reason.message : 'The camera could not be opened.')
    }
  }

  const scanImage = async (file?: File) => {
    if (!file) return
    setError('')
    const imageUrl = URL.createObjectURL(file)
    try {
      const reader = await createBarcodeReader()
      const result = await reader.decodeFromImageUrl(imageUrl)
      onCode(result.getText())
    } catch {
      setError('No barcode was found in that image. Try a clearer, closer photo.')
    } finally {
      URL.revokeObjectURL(imageUrl)
    }
  }

  return <div className={`barcode-scanner ${compact ? 'barcode-scanner--compact' : ''}`}>
    <div className="scanner-preview" hidden={!active}><video ref={videoRef} muted playsInline/><span/>{active && <Button type="button" variant="secondary" onClick={stop}>Stop camera</Button>}</div>
    {!active && <div className="scanner-actions">
      <Button type="button" variant="secondary" disabled={!cameraAvailable} onClick={start}><Camera size={18}/>Scan live</Button>
      <label className="button button--secondary image-scan-button"><ImageUp size={18}/>Scan a photo<input type="file" accept="image/*" capture="environment" onChange={event => void scanImage(event.target.files?.[0])}/></label>
    </div>}
    {!cameraAvailable && <small>Live scanning needs camera permission and HTTPS. Photo and number lookup still work.</small>}
    {error && <small className="field-error">{error}</small>}
  </div>
}
