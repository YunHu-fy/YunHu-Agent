package io.localagent.android

import org.junit.Assert.*
import org.junit.Test
import java.io.IOException
import java.io.File

class PrivatePrefixPathTest {
    private val uid = 10234
    private val appDirectory = PrivatePrefixPath.Identity(253, 900001, uid, true)

    @Test fun dataUserZeroAndLegacyAliasWithDifferentNamesReferToSameDirectory() {
        val visited = mutableListOf<String>()
        val result = PrivatePrefixPath.inspect("/data/user/0/com.termux/files", uid) { path -> visited.add(path); appDirectory }
        assertTrue(result.matches)
        result.requireMatch()
        assertEquals(listOf("/data/user/0/com.termux/files", "/data/data/com.termux/files"), visited)
    }
    @Test fun adoptedStorageMountAliasWithSameIdentityIsAccepted() {
        val result = PrivatePrefixPath.inspect("/mnt/expand/volume/user/0/com.termux/files", uid) { appDirectory }
        assertTrue(result.matches)
    }
    @Test fun identicalPathSpellingStillRequiresOwnedDirectory() {
        val result = PrivatePrefixPath.inspect(PrivatePrefixPath.FILES, uid) { appDirectory.copy(uid = 0) }
        assertFalse(result.matches)
        assertTrue(result.failure!!.contains("UID"))
    }
    @Test fun matchingOwnerOnDifferentDirectoryIsRejected() {
        val result = PrivatePrefixPath.inspect("/data/user/0/com.termux/files", uid) { path -> if (path == PrivatePrefixPath.FILES) appDirectory.copy(inode = 900002) else appDirectory }
        assertFalse(result.matches)
        try { result.requireMatch(); fail("Distinct directories must not pass") } catch (_: IllegalStateException) { }
    }
    @Test fun sameInodeOnDifferentDeviceIsRejected() {
        val result = PrivatePrefixPath.inspect("/data/user/0/com.termux/files", uid) { path -> if (path == PrivatePrefixPath.FILES) appDirectory.copy(device = 254) else appDirectory }
        assertFalse(result.matches)
    }
    @Test fun directoryAliasMustNotResolveToRegularFile() {
        val result = PrivatePrefixPath.inspect("/data/user/0/com.termux/files", uid) { path -> if (path == PrivatePrefixPath.FILES) appDirectory.copy(directory = false) else appDirectory }
        assertFalse(result.matches)
    }
    @Test fun unavailableLegacyMappingFailsClosedWithActualPathDiagnostics() {
        val actualPath = "/data/user/0/com.termux/files"
        val result = PrivatePrefixPath.inspect(actualPath, uid) { path -> if (path == PrivatePrefixPath.FILES) throw IOException("unavailable") else appDirectory }
        assertFalse(result.matches)
        assertEquals(appDirectory, result.actual)
        assertNull(result.expected)
        assertTrue(result.failure!!.contains(actualPath))
        assertTrue(result.failure.contains(PrivatePrefixPath.FILES))
        assertTrue(result.failure.contains("IOException"))
    }
    @Test fun publicationUsesFixedParentForBothRenameEndpoints() {
        val actualRoot = File("/data/user/0/com.termux/files")
        val stage = File(actualRoot, ".agent-stage-1234-5678")
        val source = PrivatePrefixPath.publicationSource(actualRoot, stage)
        assertEquals(File(PrivatePrefixPath.FILES), source.parentFile)
        assertEquals(stage.name, source.name)
    }
    @Test fun publicationRejectsNestedOrUnrelatedStageDirectories() {
        val actualRoot = File("/data/user/0/com.termux/files")
        for (stage in listOf(File(File(actualRoot, "nested"), ".agent-stage-1234"), File(actualRoot, "user-data"))) {
            try { PrivatePrefixPath.publicationSource(actualRoot, stage); fail("Only direct private staging children can be published") } catch (_: IllegalArgumentException) { }
        }
    }
    @Test fun permissionFailureDetailsAreRetainedForDiagnosis() {
        val result = PrivatePrefixPath.inspect("/data/user/0/com.termux/files", uid) { throw IOException("stat failed: EACCES (Permission denied)") }
        assertFalse(result.matches)
        assertTrue(result.failure!!.contains("EACCES"))
    }
    @Test fun inaccessibleActualDirectoryDoesNotValidateOrCreateLegacyPath() {
        val visited = mutableListOf<String>()
        val result = PrivatePrefixPath.inspect("/data/user/0/com.termux/files", uid) { path -> visited.add(path); throw SecurityException("denied") }
        assertFalse(result.matches)
        assertEquals(listOf("/data/user/0/com.termux/files"), visited)
        assertNull(result.actual)
        assertNull(result.expected)
    }
}
