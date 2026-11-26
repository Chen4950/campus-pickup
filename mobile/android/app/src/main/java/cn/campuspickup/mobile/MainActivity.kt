package cn.campuspickup.mobile

import android.app.AlertDialog
import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.activity.ComponentActivity
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.LocalTime
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {
    private val worker = Executors.newSingleThreadExecutor()
    private val settings by lazy { getSharedPreferences("pickup", MODE_PRIVATE) }
    private lateinit var content: LinearLayout
    private var api: PickupApi? = null
    private var account: JSONObject? = null
    private var station: JSONObject? = null
    private var parcels = JSONArray()
    private var route: JSONObject? = null
    private var forecast: JSONObject? = null
    private var scanned: JSONObject? = null
    private var scanCode = ""
    private var registration = false
    private var serverDraft: String? = null
    private var changingPassword = false
    private var busy = false
    private var message = ""
    private var page = "route"
    private var start = ""
    private var date = ""
    private var earliest = "10:00"
    private var latest = "20:00"
    private val found = mutableSetOf<Int>()
    private val deferred = mutableSetOf<Int>()

    private val scanner = registerForActivityResult(ScanContract()) { result ->
        result.contents?.takeIf { account?.optString("role") == "admin" }?.let(::lookup)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.rgb(15, 83, 69)
        window.navigationBarColor = Color.rgb(15, 83, 69)
        render()
    }

    override fun onDestroy() {
        worker.shutdownNow()
        super.onDestroy()
    }

    private fun perform(action: () -> Unit, success: () -> Unit = {}) {
        if (busy) return
        busy = true
        message = ""
        // Keep entered values visible while the request is running.
        content.alpha = 0.65f
        worker.execute {
            val result = runCatching(action)
            runOnUiThread {
                if (isDestroyed || isFinishing) return@runOnUiThread
                busy = false
                result.onSuccess { success() }.onFailure {
                    if (it is ApiError && it.status == 401 && account != null) clearAccount()
                    message = it.message ?: "请求失败"
                }
                content.alpha = 1f
                if (result.isSuccess || account == null && page != "login") render()
                else Toast.makeText(this, message, Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun clearAccount() {
        api = null
        account = null
        station = null
        parcels = JSONArray()
        route = null
        forecast = null
        scanned = null
        scanCode = ""
        found.clear()
        deferred.clear()
        start = ""
        date = ""
        changingPassword = false
        registration = false
        page = "route"
    }

    private fun render() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.rgb(242, 247, 245))
        }
        val heading = TextView(this).apply {
            text = "校园驿站"
            textSize = 24f
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.rgb(15, 83, 69))
            setPadding(dp(18), dp(12), dp(18), dp(12))
        }
        root.addView(heading)
        content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(12), dp(16), dp(24))
        }
        root.addView(ScrollView(this).apply { addView(content); isFillViewport = true })
        setContentView(root)
        val user = account
        if (user == null) {
            loginForm()
            return
        }
        label(user.getString("username"), 15f)
        row {
            rowButton("修改密码") { changingPassword = !changingPassword; message = ""; render() }
            rowButton("退出登录") {
                val client = api ?: return@rowButton
                perform({ client.call("/api/auth/logout", json()) }, { clearAccount() })
            }
        }
        if (message.isNotEmpty()) label(message)
        if (changingPassword) {
            val old = field("当前密码", secret = true)
            val next = field("新密码（至少 8 位）", secret = true)
            button("保存新密码") {
                val payload = json("current_password" to old.text.toString(), "new_password" to next.text.toString())
                perform({ api!!.call("/api/auth/password", payload) }, { changingPassword = false; message = "密码已修改。" })
            }
        }
        if (user.getString("role") == "admin") {
            scannerView()
            return
        }
        row {
            rowButton("取件路线") { page = "route"; render(); refresh() }
            rowButton("错峰计划") { page = "forecast"; render(); if (station == null) refresh() }
        }
        if (page == "route") routeView() else forecastView()
    }

    private fun loginForm() {
        page = "login"
        label(if (registration) "注册普通账号" else "登录", 24f)
        if (message.isNotEmpty()) label(message)
        val default = if (BuildConfig.DEBUG) "http://10.0.2.2:8000" else ""
        val address = field("服务器地址", serverDraft ?: settings.getString("server", default).orEmpty())
        val username = field("用户名")
        val password = field(if (registration) "密码（至少 8 位）" else "密码", secret = true)
        button(if (registration) "注册并登录" else "登录") {
            val server = address.text.toString().trim()
            val user = username.text.toString().trim()
            val secret = password.text.toString()
            val endpoint = if (registration) "register" else "login"
            perform({
                val client = PickupApi(server)
                val profile = client.call("/api/auth/" + endpoint, json("username" to user, "password" to secret)) as JSONObject
                api = client
                account = profile
            }, {
                settings.edit().putString("server", server).apply()
                serverDraft = null
                page = "route"
                if (account!!.getString("role") != "admin") refresh()
            })
        }
        button(if (registration) "返回登录" else "注册新账号") {
            serverDraft = address.text.toString()
            registration = !registration
            message = ""
            render()
        }
    }

    private fun refresh() {
        if (busy) return
        val client = api ?: return
        perform({
            val info = client.call("/api/station") as JSONObject
            val entries = client.call("/api/parcels/mine") as JSONArray
            val entry = info.getJSONObject("station").getString("entry_node")
            val nodes = info.getJSONObject("layout").getJSONArray("nodes").objects()
            val position = start.takeIf { id -> nodes.any { it.getString("id") == id && it.getString("type") == "shelf" } } ?: entry
            val parcelIds = entries.objects().map { it.getInt("id") }.toSet()
            found.retainAll(parcelIds)
            deferred.retainAll(parcelIds)
            val nextRoute = if (entries.length() == 0) null else client.call("/api/routes",
                json("start" to position, "excluded_ids" to JSONArray((found + deferred).toList()))) as JSONObject
            station = info
            parcels = entries
            start = position
            route = nextRoute
            if (date.isEmpty()) {
                date = info.getString("today")
                val hours = hoursFor(date, info)
                if (info.getString("current_time") >= hours.getString(1)) date = info.getString("tomorrow")
                val opening = hoursFor(date, info)
                earliest = opening.getString(0)
                latest = opening.getString(1)
            }
        })
    }

    private fun hoursFor(day: String, info: JSONObject): JSONArray {
        val weekend = LocalDate.parse(day).dayOfWeek.value >= 6
        return info.getJSONObject("station").getJSONObject("operating_hours")
            .getJSONArray(if (weekend) "weekend" else "weekday")
    }

    private fun routeView() {
        label("站内取件路线", 23f)
        button("刷新包裹和路线", ::refresh)
        val info = station ?: return
        val layout = info.getJSONObject("layout")
        val positions = layout.getJSONArray("nodes").objects()
            .filter { it.getString("type") in listOf("shelf", "entrance") }.map { it.getString("id") }
        button("当前位置 · " + start) {
            AlertDialog.Builder(this).setTitle("选择当前位置").setItems(positions.toTypedArray()) { _, index ->
                start = positions[index]
                refresh()
            }.show()
        }
        content.addView(StationMap(layout, route, start), ViewGroup.LayoutParams(-1, dp(220)))
        if (parcels.length() == 0) {
            label("当前账号暂无待取包裹。")
            return
        }
        val steps = route?.getJSONArray("stops")?.strings().orEmpty()
        if (route != null) {
            label("建议顺序 · " + (steps + listOf("核验点", "出口")).joinToString(" → "))
            label("预计步行 ${route!!.getDouble("distance_m")} 米")
            val unreachable = route!!.getJSONArray("unreachable_shelves").strings()
            if (unreachable.isNotEmpty()) label("暂时无法到达 " + unreachable.joinToString("、"))
        }
        val ranks = steps.withIndex().associate { it.value to it.index }
        parcels.objects().sortedBy { ranks[it.getString("shelf")] ?: Int.MAX_VALUE }.forEach {
            val id = it.getInt("id")
            label("${it.getString("shelf")} · 第 ${it.getString("level")} 层 · 尾号 ${it.getString("suffix")}\n${it.getString("code")}")
            if (id in found || id in deferred) {
                label(if (id in found) "已找到" else "暂未找到")
                button("重新查找") {
                    found.remove(id)
                    deferred.remove(id)
                    start = it.getString("shelf")
                    forecast = null
                    refresh()
                }
            } else {
                row {
                    rowButton("已找到") { markParcel(it, found) }
                    rowButton("暂未找到") { markParcel(it, deferred) }
                }
            }
        }
    }

    private fun markParcel(parcel: JSONObject, progress: MutableSet<Int>) {
        progress.add(parcel.getInt("id"))
        start = parcel.getString("shelf")
        forecast = null
        refresh()
    }

    private fun forecastView() {
        label("错峰计划", 23f)
        if (date.isEmpty()) {
            button("读取营业时间", ::refresh)
            return
        }
        button("到站日期 · $date") {
            val day = LocalDate.parse(date)
            DatePickerDialog(this, { _, year, month, dayOfMonth ->
                date = LocalDate.of(year, month + 1, dayOfMonth).toString()
                val hours = hoursFor(date, station!!)
                earliest = hours.getString(0)
                latest = hours.getString(1)
                forecast = null
                render()
            }, day.year, day.monthValue - 1, day.dayOfMonth).apply {
                datePicker.minDate = LocalDate.parse(station!!.getString("today"))
                    .atStartOfDay(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli()
            }.show()
        }
        row {
            rowButton("最早 $earliest") { pickTime(earliest) { earliest = it } }
            rowButton("最晚 $latest") { pickTime(latest) { latest = it } }
        }
        button("比较到站时段") {
            val payload = json("day" to date, "earliest" to earliest, "latest" to latest,
                "excluded_ids" to JSONArray((found + deferred).toList()))
            perform({ forecast = api!!.call("/api/forecasts", payload) as JSONObject })
        }
        forecast?.let { result ->
            if (!result.isNull("message")) label(result.getString("message"))
            result.getJSONArray("candidates").objects().forEach {
                label("${it.getString("time")} · 预计排队 ${it.getDouble("wait_minutes")} 分钟", 18f)
                label("常见 ${it.getDouble("usual_low_minutes")}–${it.getDouble("usual_high_minutes")} 分钟")
                if (!it.isNull("total_minutes")) label("预计全程 ${it.getDouble("total_minutes")} 分钟")
                if (it.optBoolean("may_finish_after_close")) label("预计离站时间可能晚于关门")
            }
        }
    }

    private fun pickTime(value: String, update: (String) -> Unit) {
        val time = LocalTime.parse(value)
        TimePickerDialog(this, { _, hour, minute ->
            update(LocalTime.of(hour, minute).toString())
            forecast = null
            render()
        }, time.hour, time.minute, true).show()
    }

    private fun scannerView() {
        label("扫码取件", 23f)
        button("打开相机扫码") {
            scanner.launch(ScanOptions().setPrompt("对准包裹条码或二维码").setBeepEnabled(false))
        }
        val code = field("包裹码", scanCode)
        button("查找包裹") { lookup(code.text.toString()) }
        scanned?.let { parcel ->
            label(parcel.getString("code"), 20f)
            label("${parcel.getString("username")} · ${parcel.getString("shelf")} 货架 · 尾号 ${parcel.getString("suffix")}")
            row {
                rowButton("确认取件") { closeParcel(parcel.getInt("id"), false) }
                rowButton("丢弃包裹") {
                    AlertDialog.Builder(this@MainActivity).setTitle("确认丢弃该包裹？")
                        .setNegativeButton("取消", null)
                        .setPositiveButton("丢弃") { _, _ -> closeParcel(parcel.getInt("id"), true) }.show()
                }
            }
        }
    }

    private fun lookup(code: String) {
        if (code.isBlank() || busy || api == null) return
        scanCode = code.trim()
        scanned = null
        render()
        perform({ scanned = api!!.call("/api/admin/pickup/lookup", json("code" to scanCode)) as JSONObject })
    }

    private fun closeParcel(id: Int, discard: Boolean) {
        perform({
            if (discard) api!!.call("/api/admin/parcels/$id", method = "DELETE")
            else api!!.call("/api/admin/pickup/$id", json())
        }, {
            scanned = null
            scanCode = ""
            message = if (discard) "包裹已丢弃。" else "包裹已核验出库。"
        })
    }

    private fun label(value: String, size: Float = 16f) {
        content.addView(TextView(this).apply {
            text = value
            textSize = size
            setTextColor(Color.rgb(21, 47, 45))
            setPadding(0, dp(8), 0, dp(5))
        })
    }

    private fun field(hint: String, value: String = "", secret: Boolean = false): EditText =
        EditText(this).apply {
            this.hint = hint
            setText(value)
            isSingleLine = true
            if (secret) inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            content.addView(this)
        }

    private fun button(title: String, action: () -> Unit) {
        content.addView(makeButton(title, action))
    }

    private fun makeButton(title: String, action: () -> Unit) = Button(this).apply {
        text = title
        isAllCaps = false
        setOnClickListener { if (!busy) action() }
    }

    private fun row(add: LinearLayout.() -> Unit) {
        val row = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL; add() }
        content.addView(row)
    }

    private fun LinearLayout.rowButton(title: String, action: () -> Unit) {
        addView(makeButton(title, action), LinearLayout.LayoutParams(0, -2, 1f))
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    private inner class StationMap(
        private val layout: JSONObject, private val plan: JSONObject?, private val location: String
    ) : View(this@MainActivity) {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)

        init { contentDescription = "驿站平面图" }

        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            val nodes = layout.getJSONArray("nodes").objects()
            if (nodes.isEmpty()) return
            val minX = nodes.minOf { it.getDouble("x") }
            val minY = nodes.minOf { it.getDouble("y") }
            val rangeX = (nodes.maxOf { it.getDouble("x") } - minX).coerceAtLeast(1.0)
            val rangeY = (nodes.maxOf { it.getDouble("y") } - minY).coerceAtLeast(1.0)
            val margin = dp(30)
            val points = nodes.associate {
                it.getString("id") to Pair(
                    (margin + (it.getDouble("x") - minX) / rangeX * (width - 2 * margin)).toFloat(),
                    (height - margin - (it.getDouble("y") - minY) / rangeY * (height - 2 * margin)).toFloat()
                )
            }
            canvas.drawColor(Color.WHITE)
            fun line(from: String, to: String) {
                val a = points[from] ?: return
                val b = points[to] ?: return
                canvas.drawLine(a.first, a.second, b.first, b.second, paint)
            }
            paint.color = Color.rgb(199, 217, 211)
            paint.strokeWidth = dp(5).toFloat()
            layout.getJSONArray("directed_edges").objects().forEach { line(it.getString("from"), it.getString("to")) }
            paint.color = Color.rgb(22, 119, 94)
            val path = plan?.getJSONArray("path")?.strings().orEmpty()
            path.zipWithNext().forEach { (a, b) -> line(a, b) }
            paint.textSize = dp(12).toFloat()
            paint.textAlign = Paint.Align.CENTER
            nodes.forEach {
                val id = it.getString("id")
                val point = points.getValue(id)
                paint.color = if (id == location) Color.rgb(15, 83, 69) else Color.rgb(81, 133, 120)
                canvas.drawCircle(point.first, point.second, dp(if (id == location) 7 else 5).toFloat(), paint)
                if (it.getString("type") != "aisle")
                    canvas.drawText(id, point.first, point.second - dp(10), paint)
            }
        }
    }
}

private fun JSONArray.objects() = List(length()) { getJSONObject(it) }
private fun JSONArray.strings() = List(length()) { getString(it) }
