package io.localagent.android

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

/** Device-local vault; backup/transfer is disabled by the app manifest. All operations fail closed. */
internal object KeyStoreCredentialStore {
    private const val ALIAS = "local_agent.model_keys.v1"
    private lateinit var prefs: SharedPreferences
    @Synchronized fun initialize(context: Context) { if (!::prefs.isInitialized) prefs = context.applicationContext.getSharedPreferences("model_credentials_v1", Context.MODE_PRIVATE) }
    private fun key(create: Boolean): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val existing = store.getKey(ALIAS, null)
        if (existing != null) return existing as SecretKey
        check(create) { "Stored model key is unavailable on this device" }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256).setRandomizedEncryptionRequired(true).build())
        return generator.generateKey()
    }
    @Synchronized fun read(profile: String): String {
        CredentialCipher.validateProfile(profile)
        val encrypted = prefs.getString(profile, null) ?: return ""
        return CredentialCipher.decrypt(profile, encrypted, key(false))
    }
    @Synchronized fun write(profile: String, secret: String) {
        CredentialCipher.validateProfile(profile)
        if (secret.isEmpty()) { delete(profile); return }
        val encrypted = CredentialCipher.encrypt(profile, secret, key(true))
        check(prefs.edit().putString(profile, encrypted).commit()) { "Could not persist encrypted model credential" }
    }
    @Synchronized fun delete(profile: String) {
        CredentialCipher.validateProfile(profile)
        check(prefs.edit().remove(profile).commit()) { "Could not remove model credential" }
    }
}
