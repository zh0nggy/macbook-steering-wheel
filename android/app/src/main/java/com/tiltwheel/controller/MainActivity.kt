package com.tiltwheel.controller

import android.app.Activity
import android.app.AlertDialog
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.WindowInsets
import android.view.WindowManager
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView

/** Colours matching the Mac sender in dark mode (app_common.Bar and friends). */
object Theme {
    val BACKGROUND = Color.rgb(30, 30, 30)
    val TEXT = Color.rgb(230, 230, 230)
    val MUTED = Color.rgb(150, 150, 150)
    val TROUGH = Color.rgb(0x2c, 0x2c, 0x2e)
    val BORDER = Color.rgb(0x5a, 0x5a, 0x5e)
    val CENTRE_LINE = Color.rgb(0x9a, 0x9a, 0x9a)
    val STEER = Color.parseColor("#2b7de9")
    val BOX = Color.parseColor("#2f4f78")       // same as phone_layout.py
    val BOX_LINE = Color.parseColor("#8fb4e8")
}

/**
 * Two pages:
 *  1. Connect: pick the Windows PC (found on the network, or type its IP) and
 *     tap Start sending, like the "Windows PC" box in the Mac app.
 *  2. Steering: tilt to steer, plus the touch buttons laid out in the
 *     receiver's Phone layout window (sent over the link). Stop goes back to 1.
 *
 * All steering tuning (deadzone, gamma, smoothing, invert) lives in the
 * receiver window, which also shows whether the phone is linked.
 */
class MainActivity : Activity() {
    private lateinit var sensor: SteeringSensor
    private lateinit var sender: Sender
    private lateinit var discovery: Discovery

    private lateinit var connectPage: View
    private lateinit var steerPage: View
    private lateinit var pcList: LinearLayout
    private lateinit var hostField: EditText
    private lateinit var targetLabel: TextView
    private lateinit var steerBar: Bar
    private lateinit var buttonLayer: ButtonLayer
    private lateinit var emptyHint: TextView

    private val ui = Handler(Looper.getMainLooper())
    private val prefs by lazy { getSharedPreferences("tiltwheel", MODE_PRIVATE) }
    private var shownPcs: List<Discovery.Pc>? = null
    private var port = Protocol.DEFAULT_PORT

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        sensor = SteeringSensor(this)
        sender = Sender(sensor)
        discovery = Discovery(this)
        setContentView(buildLayout())
        showPage(connect = true)
    }

    override fun onResume() {
        super.onResume()
        sensor.start()
        discovery.start()
        ui.post(refresh)
    }

    override fun onPause() {
        // Leaving the app (call, home button) must never leave the car
        // steering: stop() sends centred frames on the way out. You come back
        // to the Connect page and tap Start sending again.
        sender.stop()
        sensor.stop()
        discovery.stop()
        ui.removeCallbacks(refresh)
        showPage(connect = true)
        super.onPause()
    }

    @Deprecated("Back on the steering page means Stop, not leave the app.")
    override fun onBackPressed() {
        if (sender.isRunning) stopSending() else @Suppress("DEPRECATION") super.onBackPressed()
    }

    // --- layout ---

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun text(value: String, size: Float = 14f, color: Int = Theme.TEXT) = TextView(this).apply {
        text = value
        textSize = size
        setTextColor(color)
    }

    private fun button(label: String, onClick: () -> Unit) = Button(this).apply {
        text = label
        isAllCaps = false
        setOnClickListener { onClick() }
    }

    private fun page() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER_VERTICAL
    }

    private fun buildLayout(): View {
        connectPage = buildConnectPage()
        steerPage = buildSteerPage()
        val root = FrameLayout(this).apply {
            setBackgroundColor(Theme.BACKGROUND)
            setPadding(dp(24), dp(16), dp(24), dp(16))
            addView(connectPage)
            addView(steerPage)
        }
        // Android 15+ draws apps under the status and navigation bars.
        // Pad by their size (and any camera cutout) so nothing is hidden.
        // Older Android leaves room for the bars itself.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            root.setOnApplyWindowInsetsListener { view, insets ->
                val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                view.setPadding(bars.left + dp(24), bars.top + dp(16), bars.right + dp(24), bars.bottom + dp(16))
                insets
            }
        }
        return root
    }

    /** Page 1, laid out like the Mac app's "Windows PC" box. */
    private fun buildConnectPage(): View {
        val column = page()
        column.addView(text("Windows PC", 13f, Theme.MUTED).apply { setPadding(dp(4), 0, 0, dp(2)) })
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(10), dp(8), dp(10), dp(8))
            background = GradientDrawable().apply {
                setStroke(dp(1), Theme.BORDER)
                cornerRadius = dp(6).toFloat()
            }
        }
        pcList = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        box.addView(pcList)

        val ipRow = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        ipRow.addView(text("IP"), LinearLayout.LayoutParams(dp(28), LinearLayout.LayoutParams.WRAP_CONTENT))
        hostField = EditText(this).apply {
            setText(prefs.getString("host", ""))
            hint = "192.168.x.x"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine()
            setTextColor(Theme.TEXT)
            setHintTextColor(Theme.MUTED)
        }
        ipRow.addView(hostField, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        ipRow.addView(button("Start sending") { startSending() })
        box.addView(ipRow)
        column.addView(box)
        return column
    }

    /**
     * Page 2: a slim strip on top (target, steering bar, Calibrate, Stop) and,
     * filling the rest, the buttons from the receiver's Phone layout window.
     */
    private fun buildSteerPage(): View {
        val column = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }

        val strip = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        targetLabel = text("", 12f, Theme.MUTED)
        strip.addView(targetLabel)
        steerBar = Bar(this, Theme.STEER, centered = true).apply { contentDescription = "Steering" }
        strip.addView(steerBar, LinearLayout.LayoutParams(0, dp(18), 1f).apply {
            marginStart = dp(12); marginEnd = dp(12)
        })
        strip.addView(button("Calibrate centre") { sensor.calibrate() })
        strip.addView(button("Stop") { stopSending() })
        column.addView(strip)

        val area = FrameLayout(this).apply { setPadding(0, dp(6), 0, 0) }
        buttonLayer = ButtonLayer(this) { mask, rt, lt ->
            sender.buttons = mask
            sender.rightTrigger = rt
            sender.leftTrigger = lt
        }
        area.addView(buttonLayer)
        emptyHint = text("Add buttons in the receiver's Phone layout window\n" +
            "(click Android there). They appear here in a moment.", 13f, Theme.MUTED).apply {
            gravity = Gravity.CENTER
            isClickable = false // touches go through to the buttons
        }
        area.addView(emptyHint, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.MATCH_PARENT))
        column.addView(area, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        return column
    }

    private fun showPage(connect: Boolean) {
        connectPage.visibility = if (connect) View.VISIBLE else View.GONE
        steerPage.visibility = if (connect) View.GONE else View.VISIBLE
    }

    // --- behaviour ---

    private fun startSending() {
        val host = hostField.text.toString().trim()
        if (host.isEmpty()) {
            message("Pick your PC from the list, or type its IP.\n\n" +
                "If the list is empty, open the receiver app on Windows and press Start.")
            return
        }
        if (isPrivate(host) == false) {
            message("$host is not a local network address.\n\nUse the address shown at the " +
                "top of the Windows receiver app (192.168.x.x, 10.x.x.x or 172.16-31.x.x).")
            return
        }
        prefs.edit().putString("host", host).apply()
        hostField.clearFocus()
        (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager)
            .hideSoftInputFromWindow(hostField.windowToken, 0)
        sender.start(host, port)
        targetLabel.text = "Sending to $host"
        showPage(connect = false)
    }

    private fun stopSending() {
        sender.stop()
        showPage(connect = true)
    }

    private fun message(value: String) {
        AlertDialog.Builder(this).setTitle("Tilt Wheel").setMessage(value)
            .setPositiveButton("OK", null).show()
    }

    private fun pickPc(pc: Discovery.Pc) {
        hostField.setText(pc.ip)
        port = pc.port
        showPcs(shownPcs.orEmpty())
    }

    private fun showPcs(pcs: List<Discovery.Pc>) {
        shownPcs = pcs
        pcList.removeAllViews()
        if (pcs.isEmpty()) {
            pcList.addView(text("Looking for the Windows receiver...", color = Theme.MUTED)
                .apply { setPadding(dp(6), dp(8), dp(6), dp(8)) })
            return
        }
        val selected = hostField.text.toString().trim()
        for (pc in pcs) {
            pcList.addView(text("${pc.name}  (${pc.ip})", 15f).apply {
                setPadding(dp(6), dp(8), dp(6), dp(8))
                if (pc.ip == selected) setBackgroundColor(Theme.STEER)
                setOnClickListener { pickPc(pc) }
            })
        }
    }

    private val refresh = object : Runnable {
        override fun run() {
            if (connectPage.visibility == View.VISIBLE) {
                // Discovered PCs; fill in the only one automatically, like the Mac app.
                val pcs = discovery.recent()
                if (pcs.size == 1 && hostField.text.isBlank()) {
                    hostField.setText(pcs[0].ip)
                    port = pcs[0].port
                    shownPcs = null
                }
                if (pcs != shownPcs) showPcs(pcs)
            } else if (!sender.isRunning) {
                // The address couldn't be used (e.g. no network): back to page 1.
                showPage(connect = true)
                message("Couldn't send to that address. Check the IP and that both are on the same WiFi.")
            }
            steerBar.value = sender.steer()
            sender.layout?.let { buttonLayer.boxes = it }
            emptyHint.visibility = if (buttonLayer.boxes.isEmpty()) View.VISIBLE else View.GONE
            ui.postDelayed(this, 50)
        }
    }

    companion object {
        /** Port of mac_sender.is_private: true/false for an IPv4, null for a hostname. */
        fun isPrivate(host: String): Boolean? {
            val parts = host.split(".")
            if (parts.size != 4) return null
            val a = parts[0].toIntOrNull() ?: return null
            val b = parts[1].toIntOrNull() ?: return null
            return (a == 192 && b == 168) || a == 10 || (a == 172 && b in 16..31) || a == 127
        }
    }
}
