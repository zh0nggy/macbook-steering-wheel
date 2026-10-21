package com.tiltwheel.controller

import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.SocketTimeoutException

/**
 * The sender_app.SenderEngine loop for the phone: tilt steering, plus whichever
 * on-screen buttons are held (`buttons`, `rightTrigger`, `leftTrigger`, set by
 * the steering page). The packet is the full v3 frame, so the receiver needs
 * nothing new to drive the pad.
 *
 * The receiver also sends the button layout from its Phone layout window;
 * the newest one is in `layout` for the screen to draw.
 *
 * No tuning here: +-FULL_SCALE_DEGREES of rotation goes out as +-1, and the
 * receiver's Range (Android tuning), deadzone, gamma, smoothing and invert do
 * the rest.
 *
 * Sends when anything changes, capped at MAX_RATE (a button press goes out at
 * once), and at least every KEEPALIVE so the receiver's failsafe never fires
 * while you hold still.
 */
class Sender(private val sensor: SteeringSensor) {
    companion object {
        const val MAX_RATE = 250.0      // packets/sec ceiling
        const val KEEPALIVE = 0.01      // always send at least every 10 ms
        const val FULL_SCALE_DEGREES = 90.0  // must match PHONE_FULL_SCALE in receiver_app.pyw
    }

    @Volatile var target: String? = null
        private set

    // Written by the screen, read by the send loop.
    @Volatile var buttons = 0
    @Volatile var rightTrigger = 0.0
    @Volatile var leftTrigger = 0.0

    /** Newest layout from the receiver, or null until one arrives. */
    @Volatile var layout: List<Protocol.Box>? = null
        private set

    @Volatile private var running = false
    private var thread: Thread? = null

    val isRunning get() = running

    /** -1 full left .. +1 full right. */
    fun steer() = Protocol.clamp(sensor.offset() / FULL_SCALE_DEGREES, -1.0, 1.0)

    fun start(host: String, port: Int) {
        stop()
        target = host
        running = true
        thread = Thread({ run(host, port) }, "sender").apply {
            priority = Thread.MAX_PRIORITY
            start()
        }
    }

    /** Stops sending; the loop centres the car and releases everything on the way out. */
    fun stop() {
        running = false
        thread?.join(1000)
        thread = null
        target = null
    }

    private fun run(host: String, port: Int) {
        val socket: DatagramSocket
        val address: InetAddress
        try {
            address = InetAddress.getByName(host)
            socket = DatagramSocket().apply {
                trafficClass = 0xB8 // DSCP EF, same "voice" class as app_common.low_latency_socket
                soTimeout = 1       // receive() doubles as the loop's 1 ms sleep
            }
        } catch (_: Exception) {
            running = false
            target = null // lets the screen retry on its next refresh
            return
        }

        fun send(steer: Double, rt: Double, lt: Double, mask: Int, seq: Int) {
            val data = Protocol.pack(steer, rt, lt, seq, mask, monotonicSeconds())
            try {
                socket.send(DatagramPacket(data, data.size, address, port))
            } catch (_: Exception) {
                // Network blip; the receiver's failsafe covers the gap.
            }
        }

        var seq = 0
        var lastSend = 0.0
        var lastFrame: List<Long>? = null
        // Big enough for a layout of every button (about 40 bytes each).
        val buf = ByteArray(4096)

        while (running) {
            val now = monotonicSeconds()
            val steer = steer()
            val rt = rightTrigger
            val lt = leftTrigger
            val mask = buttons
            val frame = listOf(Math.round(steer * 1e4), Math.round(rt * 1e3), Math.round(lt * 1e3), mask.toLong())
            val since = now - lastSend
            val pressChanged = lastFrame == null || lastFrame[3] != frame[3]
            if (pressChanged || (frame != lastFrame && since >= 1.0 / MAX_RATE) || since >= KEEPALIVE) {
                send(steer, rt, lt, mask, seq++)
                lastSend = now
                lastFrame = frame
            }
            readReplies(socket, buf)
        }

        // Centre the car and release every button so nothing stays held.
        repeat(10) {
            send(0.0, 0.0, 0.0, 0, seq++)
            Thread.sleep(10)
        }
        socket.close()
    }

    /**
     * Bounce the receiver's PINGs back so its window can show a ping, and keep
     * the newest layout. Its echoes of our own timestamps are read and dropped:
     * the phone doesn't show a ping, but draining them keeps the buffer empty.
     */
    private fun readReplies(socket: DatagramSocket, buf: ByteArray) {
        while (true) {
            val packet = DatagramPacket(buf, buf.size)
            try {
                socket.receive(packet)
            } catch (_: SocketTimeoutException) {
                return
            } catch (_: Exception) {
                return
            }
            Protocol.parseLayout(packet.data, packet.length)?.let {
                if (it != layout) layout = it
                continue
            }
            val pong = Protocol.pingToPong(packet.data, packet.length) ?: continue
            try {
                socket.send(DatagramPacket(pong, pong.size, packet.socketAddress))
            } catch (_: Exception) {}
        }
    }
}
