package com.tiltwheel.controller

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.view.HapticFeedbackConstants
import android.view.MotionEvent
import android.view.View

/**
 * Draws the receiver's Phone layout as touch buttons, each at the same place
 * and size (fractions of this view) as in the editor. A button is held while
 * any finger is on it, so several can be held at once, and sliding a finger
 * from one to another moves the press like on a real pad.
 *
 * onChange(buttons, rightTrigger, leftTrigger) fires whenever the held set
 * changes: buttons is the protocol bitmask, RT / LT are 0 or 1.
 */
class ButtonLayer(
    context: Context,
    private val onChange: (Int, Double, Double) -> Unit,
) : View(context) {

    var boxes: List<Protocol.Box> = emptyList()
        set(value) {
            if (value == field) return
            field = value
            held.clear()
            report()
            invalidate()
        }

    private val held = HashSet<Int>()   // indexes into boxes
    private val density = resources.displayMetrics.density
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 2 * density
    }
    private val text = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textAlign = Paint.Align.CENTER
        isFakeBoldText = true
    }
    private val rect = RectF()

    private fun rectOf(box: Protocol.Box) = RectF(
        (box.x * width).toFloat(), (box.y * height).toFloat(),
        ((box.x + box.w) * width).toFloat(), ((box.y + box.h) * height).toFloat())

    /** Topmost box under (x, y): later boxes are drawn on top, as in the editor. */
    private fun hit(x: Float, y: Float): Int? =
        boxes.indices.lastOrNull { rectOf(boxes[it]).contains(x, y) }

    @SuppressLint("ClickableViewAccessibility")
    override fun onTouchEvent(event: MotionEvent): Boolean {
        val now = HashSet<Int>()
        val lifting = when (event.actionMasked) {
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> -1                // all fingers
            MotionEvent.ACTION_POINTER_UP -> event.actionIndex                    // this finger
            else -> null
        }
        if (lifting != -1) {
            for (i in 0 until event.pointerCount) {
                if (i == lifting) continue
                hit(event.getX(i), event.getY(i))?.let { now.add(it) }
            }
        }
        if (now != held) {
            if ((now - held).isNotEmpty()) performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
            held.clear()
            held.addAll(now)
            report()
            invalidate()
        }
        // Touches outside every box still count as ours, so a finger that
        // starts on empty screen can slide onto a button.
        return true
    }

    private fun report() {
        var mask = 0
        var rt = 0.0
        var lt = 0.0
        for (i in held) {
            when (val target = boxes[i].target) {
                "RT" -> rt = 1.0
                "LT" -> lt = 1.0
                else -> if (target in Protocol.BUTTONS) mask = mask or Protocol.bit(target)
            }
        }
        onChange(mask, rt, lt)
    }

    override fun onDraw(canvas: Canvas) {
        val radius = 8 * density
        for ((i, box) in boxes.withIndex()) {
            rect.set(rectOf(box))
            val base = FACE_COLORS[box.target] ?: Theme.BOX
            val pressed = i in held
            fill.color = if (pressed) base else Color.argb(150, Color.red(base), Color.green(base), Color.blue(base))
            canvas.drawRoundRect(rect, radius, radius, fill)
            line.color = if (pressed) Color.WHITE else Theme.BOX_LINE
            canvas.drawRoundRect(rect, radius, radius, line)
            // Label sized to the box, like the editor.
            val label = LABELS[box.target] ?: box.target
            text.textSize = minOf(rect.width() / (label.length * 0.7f + 0.6f), rect.height() * 0.45f)
            canvas.drawText(label, rect.centerX(), rect.centerY() - (text.ascent() + text.descent()) / 2, text)
        }
    }

    companion object {
        // Same short labels and face-button colours as phone_layout.py.
        val LABELS = mapOf(
            "VIEW" to "View", "MENU" to "Menu", "GUIDE" to "Xbox",
            "DPAD_UP" to "Up", "DPAD_DOWN" to "Down", "DPAD_LEFT" to "Left", "DPAD_RIGHT" to "Right",
        )
        val FACE_COLORS = mapOf(
            "A" to Color.parseColor("#2fa84f"), "B" to Color.parseColor("#d64545"),
            "X" to Color.parseColor("#2b7de9"), "Y" to Color.parseColor("#d9a400"),
        )
    }
}
