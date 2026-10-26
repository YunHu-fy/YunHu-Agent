package io.localagent.android

import org.junit.Assert.*
import org.junit.Test
import java.util.Base64
import javax.crypto.KeyGenerator

class CredentialCipherTest {
    private fun key() = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
    @Test fun newCipherInstanceDecryptsPersistedValue() {
        val key = key()
        val saved = CredentialCipher.encrypt("model-a", "sk-persist-secret", key)
        assertEquals("sk-persist-secret", CredentialCipher.decrypt("model-a", saved, key))
        assertFalse(saved.contains("sk-persist-secret"))
    }
    @Test fun sameSecretGetsDifferentNonceEverySave() {
        val key = key()
        assertNotEquals(CredentialCipher.encrypt("model-a", "same-key", key), CredentialCipher.encrypt("model-a", "same-key", key))
    }
    @Test fun ciphertextCannotBeCopiedToAnotherModelProfile() {
        val key = key()
        val saved = CredentialCipher.encrypt("model-a", "sk-one", key)
        try { CredentialCipher.decrypt("model-b", saved, key); fail("AAD must bind to profile") } catch (_: javax.crypto.AEADBadTagException) { }
    }
    @Test fun tamperingIsRejected() {
        val key = key()
        val bytes = Base64.getDecoder().decode(CredentialCipher.encrypt("model-a", "sk-one", key))
        bytes[bytes.lastIndex] = (bytes.last().toInt() xor 1).toByte()
        try { CredentialCipher.decrypt("model-a", Base64.getEncoder().encodeToString(bytes), key); fail("Tag must reject tampering") } catch (_: javax.crypto.AEADBadTagException) { }
    }
    @Test fun differentDeviceKeyCannotReadPersistedCredential() {
        val encrypted = CredentialCipher.encrypt("model-a", "sk-one", key())
        try { CredentialCipher.decrypt("model-a", encrypted, key()); fail("Wrong key must fail") } catch (_: javax.crypto.AEADBadTagException) { }
    }
    @Test fun credentialAndProfileValidationRejectsControlOrUnsafeIdentity() {
        try { CredentialCipher.encrypt("../model", "secret", key()); fail("Unsafe profile") } catch (_: IllegalArgumentException) { }
        try { CredentialCipher.encrypt("model", "secret\nheader", key()); fail("Invalid credential") } catch (_: IllegalArgumentException) { }
    }
}
