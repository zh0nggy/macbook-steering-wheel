package com.tiltwheel.controller

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.view.View

/**
 * Port of app_common.Bar: horizontal meter. centered = true draws -1..+1 from
 * the middle (steering), otherwise 0..1 from the left (triggers).
 */
class Bar(context: Context, private val color: Int, private val centered: Boolean) : View(context) {
    var value = 0.0
        set(v) {
            if (v != field) {
                field = v
                invalidate()
            }
        }

    private val paint = Paint()
    private val density = context.resources.displayMetrics.density

    override fun onDraw(canvas: Canvas) {
        val w = width.toFloat()
        val h = height.toFloat()
        paint.style = Paint.Style.FILL
        paint.color = Theme.TROUGH
        canvas.drawRect(0f, 0f, w, h, paint)

        paint.color = color
        if (centered) {
            val mid = w / 2f
            val x = mid + Protocol.clamp(value, -1.0, 1.0).toFloat() * mid
            canvas.drawRect(minOf(mid, x), 0f, maxOf(mid, x), h, paint)
            paint.color = Theme.CENTRE_LINE
            canvas.drawRect(mid - density / 2f, 0f, mid + density / 2f, h, paint)
        } else {
            canvas.drawRect(0f, 0f, Protocol.clamp(value, 0.0, 1.0).toFloat() * w, h, paint)
        }

        paint.style = Paint.Style.STROKE
        paint.strokeWidth = density
        paint.color = Theme.BORDER
        canvas.drawRect(density / 2f, density / 2f, w - density / 2f, h - density / 2f, paint)
    }
}
