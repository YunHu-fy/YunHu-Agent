# Python reflection and pinned JNI names must remain stable.
-keep class io.localagent.android.DeviceBridge { public static *; }
-keep class io.localagent.android.ShizukuUserService { *; }
-keep class io.localagent.android.IDeviceUserService** { *; }
-keep class com.termux.terminal.** { *; }
-keep class com.termux.view.** { *; }
-keep class com.chaquo.python.** { *; }
