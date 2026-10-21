package com.tiltwheel.controller

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Expected bytes come from the Python side, so a mismatch here is a dead wheel
 * on the real receiver. Regenerate with:
 *   python -c "import protocol,app_common; print(protocol.pack(-0.5,0.75,0.25,123456,
 *     protocol.BUTTON_BIT['A']|protocol.BUTTON_BIT['RB']|protocol.BUTTON_BIT['DPAD_RIGHT'],
 *     timestamp=1234.5).hex(), app_common.pack_echo(1234.5).hex(), app_common.pack_ping(1234.5).hex())"
 */
class ProtocolTest {
    private fun hex(s: String) = ByteArray(s.length / 2) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }

    @Test
    fun packMatchesPython() {
        val buttons = Protocol.bit("A") or Protocol.bit("RB") or Protocol.bit("DPAD_RIGHT")
        val bytes = Protocol.pack(-0.5, 0.75, 0.25, 123456, buttons, 1234.5)
        assertEquals(Protocol.PACKET_SIZE, bytes.size)
        assertArrayEquals(hex("0340934a0000000000bf0000003f4000003e8000000001e2404021"), bytes)
    }

    @Test
    fun packClampsLikePython() {
        val wild = Protocol.pack(5.0, -1.0, 2.0, 0, 0, 0.0)
        val sane = Protocol.pack(1.0, 0.0, 1.0, 0, 0, 0.0)
        assertArrayEquals(sane, wild)
    }

    @Test
    fun echoAndPing() {
        assertEquals(1234.5, Protocol.unpackEcho(hex("54574543484f40934a0000000000"), 14)!!, 0.0)
        val ping = hex("545750494e4740934a0000000000")
        assertNull(Protocol.unpackEcho(ping, 14))
        val pong = Protocol.pingToPong(ping, 14)!!
        assertEquals("TWPONG", String(pong, 0, 6, Charsets.US_ASCII))
        assertArrayEquals(ping.copyOfRange(6, 14), pong.copyOfRange(6, 14))
    }

    @Test
    fun layoutFromPython() {
        // app_common.pack_layout([...A, DPAD_UP, RT...])
        val data = """TWLAYO[["A",0.1,0.25,0.14,0.18],["DPAD_UP",0.0,0.82,0.3,0.18],["RT",0.86,0.0,0.14,1.0]]"""
            .toByteArray()
        val boxes = Protocol.parseLayout(data, data.size)!!
        assertEquals(listOf(
            Protocol.Box("A", 0.1, 0.25, 0.14, 0.18),
            Protocol.Box("DPAD_UP", 0.0, 0.82, 0.3, 0.18),
            Protocol.Box("RT", 0.86, 0.0, 0.14, 1.0),
        ), boxes)
    }

    @Test
    fun layoutEdgeCases() {
        val empty = "TWLAYO[]".toByteArray()
        assertEquals(emptyList<Protocol.Box>(), Protocol.parseLayout(empty, empty.size))
        val notLayout = "TWPING12345678".toByteArray()
        assertNull(Protocol.parseLayout(notLayout, notLayout.size))
        // A bad row is skipped, the good one kept.
        val mixed = """TWLAYO[["A",0.1,0.2],["B",0.5,0.5,0.1,0.1]]""".toByteArray()
        assertEquals(listOf(Protocol.Box("B", 0.5, 0.5, 0.1, 0.1)), Protocol.parseLayout(mixed, mixed.size))
    }

    @Test
    fun beacon() {
        val data = "TILTWHEEL1 5005 GAMING-PC".toByteArray()
        assertEquals(Protocol.Beacon(5005, "GAMING-PC"), Protocol.parseBeacon(data, data.size, "x"))
        val junk = "HELLO 5005".toByteArray()
        assertNull(Protocol.parseBeacon(junk, junk.size, "x"))
    }

    @Test
    fun wrap() {
        assertEquals(-170.0, wrapDegrees(190.0), 1e-9)
        assertEquals(170.0, wrapDegrees(-190.0), 1e-9)
        assertEquals(0.0, wrapDegrees(360.0), 1e-9)
    }
}
