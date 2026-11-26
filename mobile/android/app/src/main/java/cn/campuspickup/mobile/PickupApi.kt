package cn.campuspickup.mobile

import org.json.JSONObject
import org.json.JSONTokener
import java.net.HttpURLConnection
import java.net.URI

class ApiError(val status: Int, message: String) : Exception(message)

class PickupApi(val address: String) {
    private val base = URI(address.trim().trimEnd('/')).also {
        val allowed = it.scheme == "https" || (BuildConfig.DEBUG && it.scheme == "http")
        require(allowed && it.host != null && it.userInfo == null &&
            it.query == null && it.fragment == null && it.path.isEmpty()) {
            "请输入服务器地址，例如 https://pickup.example.com"
        }
    }
    private var session: String? = null

    fun call(path: String, body: JSONObject? = null, method: String = if (body == null) "GET" else "POST"): Any {
        val connection = base.resolve(path).toURL().openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 8000
            connection.readTimeout = 10000
            connection.setRequestProperty("Accept", "application/json")
            session?.let { connection.setRequestProperty("Cookie", it) }
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            val status = connection.responseCode
            val successful = status in 200..299
            val raw = (if (successful) connection.inputStream else connection.errorStream)
                ?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (!successful) {
                val detail = runCatching { JSONObject(raw).opt("detail") as? String }.getOrNull()
                throw ApiError(status, detail ?: "请求失败（HTTP $status）")
            }
            connection.headerFields.entries
                .filter { it.key.equals("Set-Cookie", ignoreCase = true) }
                .flatMap { it.value }
                .firstOrNull { it.startsWith("pickup_session=") }
                ?.let { session = it.substringBefore(';').takeUnless { cookie -> cookie.endsWith('=') } }
            return JSONTokener(raw).nextValue()
        } finally {
            connection.disconnect()
        }
    }
}

fun json(vararg pairs: Pair<String, Any>): JSONObject = JSONObject().apply {
    for ((name, value) in pairs) put(name, value)
}
