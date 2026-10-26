package io.localagent.android;

interface IDeviceUserService {
    String commandStart(String requestJson) = 1;
    String commandPoll(String id, int after) = 2;
    String commandCancel(String id) = 3;
    String resultSlice(String id, String stream, int offset) = 4;
    void cancelAll() = 5;
    void destroy() = 16777114;
}
