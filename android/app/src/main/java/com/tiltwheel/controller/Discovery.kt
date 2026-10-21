package com.tiltwheel.controller

import android.content.Context
import android.net.wifi.WifiManager
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import java.net.SocketTimeoutException

/**
 * Port of app_common.BeaconListener: lists every receiver broadcasting on
 * BEACON_PORT. Holds a MulticastLock because many phones filter broadcast
 * packets while the screen is on battery saving, and the list stays empty.
 */
class Discovery(context: Context) {
    data class Pc(val ip: String, val port: Int, val name: String)

    private val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
    private val lock = wifi.createMulticastLock("tiltwheel-discovery").apply { setReferenceCounted(false) }
    private val found = HashMap<String, Pair<Pc, Double>>()
    @Volatile private var running = false
    private var socket: DatagramSocket? = null
    @Volatile var error: String? = null
        private set

    fun start() {
        if (running) return
        running = true
        lock.acquire()
        Thread({ run() }, "discovery").apply { isDaemon = true }.start()
    }

    private fun run() {
        val sock = try {
            DatagramSocket(null).apply {
                reuseAddress = true
                broadcast = true
                soTimeout = 500
                bind(InetSocketAddress(Protocol.BEACON_PORT))
            }
        } catch (e: Exception) {
            error = "discovery: ${e.message}"
            running = false
            return
        }
        socket = sock
        val buf = ByteArray(256)
        while (running) {
            val packet = DatagramPacket(buf, buf.size)
            try {
                sock.receive(packet)
            } catch (_: SocketTimeoutException) {
                continue
            } catch (_: Exception) {
                break
            }
            val ip = packet.address.hostAddress ?: continue
            val beacon = Protocol.parseBeacon(packet.data, packet.length, ip) ?: continue
            synchronized(found) { found[ip] = Pc(ip, beacon.port, beacon.name) to monotonicSeconds() }
        }
        sock.close()
    }

    /** PCs heard within `maxAge` seconds, sorted by IP. */
    fun recent(maxAge: Double = 4.0): List<Pc> {
        val now = monotonicSeconds()
        return synchronized(found) {
            found.values.filter { now - it.second <= maxAge }.map { it.first }.sortedBy { it.ip }
        }
    }

    fun stop() {
        running = false
        socket?.close()
        if (lock.isHeld) lock.release()
    }
}
