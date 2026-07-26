import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BarcodeScanner } from './BarcodeScanner'

const scannerMocks = vi.hoisted(() => ({
  constructorHints: undefined as Map<unknown, unknown> | undefined,
  controls: { stop: vi.fn() },
  decodeFromImageUrl: vi.fn(),
  decodeFromVideoDevice: vi.fn(),
}))

vi.mock('@zxing/library', () => ({ DecodeHintType: { TRY_HARDER: 'try-harder' } }))
vi.mock('@zxing/browser', () => ({
  BrowserMultiFormatReader: class {
    constructor(hints: Map<unknown, unknown>) {
      scannerMocks.constructorHints = hints
    }

    decodeFromImageUrl = scannerMocks.decodeFromImageUrl
    decodeFromVideoDevice = scannerMocks.decodeFromVideoDevice
  },
}))

describe('BarcodeScanner', () => {
  beforeEach(() => {
    scannerMocks.constructorHints = undefined
    scannerMocks.controls.stop.mockReset()
    scannerMocks.decodeFromImageUrl.mockReset()
    scannerMocks.decodeFromVideoDevice.mockReset().mockResolvedValue(scannerMocks.controls)
    Object.defineProperty(window, 'isSecureContext', { configurable: true, value: true })
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn() },
    })
  })

  it('keeps ZXing attached to the same video element when live scanning starts', async () => {
    const user = userEvent.setup()
    const { container } = render(<BarcodeScanner onCode={vi.fn()}/>)
    const videoBeforeStart = container.querySelector('video')

    await user.click(screen.getByRole('button', { name: /scan live/i }))

    await waitFor(() => expect(scannerMocks.decodeFromVideoDevice).toHaveBeenCalled())
    const videoPassedToZxing = scannerMocks.decodeFromVideoDevice.mock.calls[0][1]
    expect(videoPassedToZxing).toBe(videoBeforeStart)
    expect(container.querySelector('video')).toBe(videoBeforeStart)
    expect(videoBeforeStart).toBeVisible()
    expect(scannerMocks.constructorHints?.get('try-harder')).toBe(true)
  })

  it('uses tolerant decoding for barcode photos and releases the object URL', async () => {
    const user = userEvent.setup()
    const onCode = vi.fn()
    const createObjectURL = vi.fn().mockReturnValue('blob:barcode-photo')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL })
    scannerMocks.decodeFromImageUrl.mockResolvedValue({ getText: () => '4056489519812' })
    render(<BarcodeScanner onCode={onCode}/>)

    await user.upload(screen.getByLabelText(/scan a photo/i), new File(['photo'], 'barcode.jpg', { type: 'image/jpeg' }))

    await waitFor(() => expect(onCode).toHaveBeenCalledWith('4056489519812'))
    expect(scannerMocks.constructorHints?.get('try-harder')).toBe(true)
    expect(scannerMocks.decodeFromImageUrl).toHaveBeenCalledWith('blob:barcode-photo')
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:barcode-photo')
  })
})
