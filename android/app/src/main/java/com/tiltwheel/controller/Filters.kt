package com.tiltwheel.controller

import kotlin.math.PI
import kotlin.math.abs

/**
 * Port of app_common.OneEuroFilter: heavy smoothing when the phone is still,
 * light smoothing when you turn fast, so you get neither jitter nor lag.
 */
class OneEuroFilter(
    @Volatile var minCutoff: Double = 1.0,
    @Volatile var beta: Double = 0.3,
    private val dCutoff: Double = 1.0,
) {
    var value: Double? = null
        private set
    private var speed = 0.0

    private fun alpha(cutoff: Double, dt: Double): Double {
        val tau = 1.0 / (2.0 * PI * cutoff)
        return 1.0 / (1.0 + tau / dt)
    }

    fun reset() {
        value = null
        speed = 0.0
    }

    fun update(x: Double, dt: Double): Double {
        val current = value
        if (current == null || dt <= 0.0) {
            value = x
            return x
        }
        val rawSpeed = (x - current) / dt
        speed += (rawSpeed - speed) * alpha(dCutoff, dt)
        val cutoff = minCutoff + beta * abs(speed)
        val next = current + (x - current) * alpha(cutoff, dt)
        value = next
        return next
    }
}

/** Port of app_common.RollingStats: average and max of the last `window` seconds. */
class RollingStats(private val window: Double = 1.0) {
    private val samples = ArrayDeque<Pair<Double, Double>>()

    @Synchronized
    fun add(value: Double, now: Double) {
        samples.addLast(now to value)
        trim(now)
    }

    @Synchronized
    fun count(now: Double): Int {
        trim(now)
        return samples.size
    }

    /** (average, maximum), or null if nothing arrived in the window. */
    @Synchronized
    fun summary(now: Double): Pair<Double, Double>? {
        trim(now)
        if (samples.isEmpty()) return null
        return samples.sumOf { it.second } / samples.size to samples.maxOf { it.second }
    }

    private fun trim(now: Double) {
        while (samples.isNotEmpty() && samples.first().first < now - window) samples.removeFirst()
    }
}

fun wrapDegrees(deg: Double) = ((deg + 180.0) % 360.0 + 360.0) % 360.0 - 180.0

/** Monotonic seconds, the same kind of clock as Python's time.monotonic(). */
fun monotonicSeconds() = System.nanoTime() / 1e9
