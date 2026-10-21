package com.tiltwheel.controller

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Kotlin copy of protocol.py (WIRE_VERSION 3) plus the ping/echo/beacon bits of
 * app_common.py. The receiver drops any packet that doesn't match byte for byte,
 * with no error, so ProtocolTest checks these against bytes produced by the
 * Python code. If you change protocol.py, update both and rerun the test.
 */
object Protocol {
    const val WIRE_VERSION = 3
    const val DEFAULT_PORT = 5005

    // "!BdfffIH": version, timestamp, steer, right_trigger, left_trigger, seq, buttons
    const val PACKET_SIZE = 1 + 8 + 4 + 4 + 4 + 4 + 2

    /** Bit order of the `buttons` field, same as protocol.BUTTONS. */
    val BUTTONS = listOf(
        "A", "B", "X", "Y",
        "LB", "RB",
        "VIEW", "MENU", "GUIDE",
        "LS", "RS",
        "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
    )

    fun bit(name: String): Int {
        val index = BUTTONS.indexOf(name)
        require(index >= 0) { "unknown button $name" }
        return 1 shl index
    }

    fun clamp(value: Double, low: Double, high: Double) =
        if (value < low) low else if (value > high) high else value

    /** One control frame, ready to send. `timestamp` is seconds on our own monotonic clock. */
    fun pack(
        steer: Double,
        rightTrigger: Double,
        leftTrigger: Double,
        seq: Int,
        buttons: Int,
        timestamp: Double,
    ): ByteArray {
        val buf = ByteBuffer.allocate(PACKET_SIZE).order(ByteOrder.BIG_ENDIAN)
        buf.put(WIRE_VERSION.toByte())
        buf.putDouble(timestamp)
        buf.putFloat(clamp(steer, -1.0, 1.0).toFloat())
        buf.putFloat(clamp(rightTrigger, 0.0, 1.0).toFloat())
        buf.putFloat(clamp(leftTrigger, 0.0, 1.0).toFloat())
        buf.putInt(seq) // unsigned on the wire; Int wraps the same way as `seq & 0xFFFFFFFF`
        buf.putShort((buttons and 0xFFFF).toShort())
        return buf.array()
    }

    // --- app_common.py: discovery beacon ---

    const val BEACON_PORT = 5006
    const val BEACON_MAGIC = "TILTWHEEL1"

    data class Beacon(val port: Int, val name: String)

    /** Parses "TILTWHEEL1 <port> <hostname>", or null if it isn't a beacon. */
    fun parseBeacon(data: ByteArray, length: Int, fallbackName: String): Beacon? {
        val parts = String(data, 0, length, Charsets.UTF_8).split(" ", limit = 3)
        if (parts.size < 2 || parts[0] != BEACON_MAGIC) return null
        val port = parts[1].toIntOrNull() ?: return null
        return Beacon(port, parts.getOrNull(2) ?: fallbackName)
    }

    // --- app_common.py: latency probes, struct "!6sd" ---

    const val ECHO_SIZE = 6 + 8
    private val ECHO_MAGIC = "TWECHO".toByteArray(Charsets.US_ASCII)
    private val PING_MAGIC = "TWPING".toByteArray(Charsets.US_ASCII)
    private val PONG_MAGIC = "TWPONG".toByteArray(Charsets.US_ASCII)

    private fun hasMagic(data: ByteArray, length: Int, magic: ByteArray): Boolean {
        if (length != ECHO_SIZE) return false
        for (i in magic.indices) if (data[i] != magic[i]) return false
        return true
    }

    /** Our own frame timestamp bounced back by the receiver, or null. */
    fun unpackEcho(data: ByteArray, length: Int): Double? =
        if (hasMagic(data, length, ECHO_MAGIC)) ByteBuffer.wrap(data, 6, 8).double else null

    // --- app_common.py: phone layout, "TWLAYO" + JSON [[target, x, y, w, h], ...] ---

    /** One on-screen button. x, y = top-left, w, h = size; fractions of the screen. */
    data class Box(val target: String, val x: Double, val y: Double, val w: Double, val h: Double)

    private val LAYOUT_MAGIC = "TWLAYO".toByteArray(Charsets.US_ASCII)

    /**
     * The receiver's layout, or null if this isn't a layout packet. Unknown
     * targets (e.g. "RT"/"LT", which aren't bits) are kept: the screen decides
     * what each does. Bad rows are skipped rather than failing the whole layout.
     */
    fun parseLayout(data: ByteArray, length: Int): List<Box>? {
        if (length < LAYOUT_MAGIC.size) return null
        for (i in LAYOUT_MAGIC.indices) if (data[i] != LAYOUT_MAGIC[i]) return null
        val json = String(data, LAYOUT_MAGIC.size, length - LAYOUT_MAGIC.size, Charsets.UTF_8).trim()
        if (!json.startsWith("[") || !json.endsWith("]")) return null
        // The format is fixed and flat (["A",0.1,0.2,0.14,0.18] per row, target
        // names have no quotes or brackets), so a regex does; it also keeps the
        // parser testable off-device, where org.json isn't available.
        val boxes = ArrayList<Box>()
        val row = Regex("""\[\s*"([A-Z_]+)"\s*,([^\[\]]*)\]""")
        for (match in row.findAll(json.substring(1, json.length - 1))) {
            val nums = match.groupValues[2].split(",").map { it.trim().toDoubleOrNull() }
            if (nums.size != 4 || nums.any { it == null || it.isNaN() }) continue
            val (x, y, w, h) = nums.map { it!! }
            boxes.add(Box(match.groupValues[1], clamp(x, 0.0, 1.0), clamp(y, 0.0, 1.0),
                clamp(w, 0.01, 1.0), clamp(h, 0.01, 1.0)))
        }
        return boxes
    }

    /** If this is the receiver's PING, the PONG bytes to send back; else null. */
    fun pingToPong(data: ByteArray, length: Int): ByteArray? {
        if (!hasMagic(data, length, PING_MAGIC)) return null
        val pong = data.copyOf(ECHO_SIZE)
        PONG_MAGIC.copyInto(pong)
        return pong
    }
}
