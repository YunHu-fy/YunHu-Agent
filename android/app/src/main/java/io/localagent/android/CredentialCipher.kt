package io.localagent.android

import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** AES-GCM binds each ciphertext to its model profile; plaintext never reaches preferences. */
internal object CredentialCipher {
    private val profilePattern = Regex("[A-Za-z0-9_-]{1,100}")
    fun validateProfile(profile: String) { require(profilePattern.matches(profile)) { "Invalid model profile ID" } }
    private fun aad(profile: String): ByteArray { validateProfile(profile); return ("local-agent.model-key.v1:" + profile).toByteArray(Charsets.UTF_8) }
    fun encrypt(profile: String, secret: String, key: SecretKey): String {
        require(secret.length <= 8192 && secret.none { it.code < 32 }) { "Invalid API key" }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key)
        check(cipher.iv.size == 12) { "Unexpected credential nonce size" }
        cipher.updateAAD(aad(profile))
        return Base64.getEncoder().encodeToString(byteArrayOf(1) + cipher.iv + cipher.doFinal(secret.toByteArray(Charsets.UTF_8)))
    }
    fun decrypt(profile: String, encrypted: String, key: SecretKey): String {
        val data = Base64.getDecoder().decode(encrypted)
        require(data.size >= 29 && data.size <= 32768 && data[0] == 1.toByte()) { "Invalid credential format" }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, data.copyOfRange(1, 13)))
        cipher.updateAAD(aad(profile))
        return cipher.doFinal(data.copyOfRange(13, data.size)).toString(Charsets.UTF_8)
    }
}
