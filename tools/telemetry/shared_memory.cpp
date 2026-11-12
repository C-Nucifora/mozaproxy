#include "packet.hpp"
#include <cstdio>
#include <cstdlib>
#include <utility>
#ifdef MOZAPROXY_LMU
#include <SharedMemoryInterface.hpp> // Provided by the game; never redistributed.
static_assert(sizeof(long) == 4 && sizeof(size_t) == 8, "LMU requires the Windows x64 ABI");
#endif

struct Mapping {
    HANDLE handle = nullptr;
    const unsigned char* data = nullptr;
    bool open(const char* name, size_t size) {
        handle = OpenFileMappingA(FILE_MAP_READ, FALSE, name);
        if (!handle) return false;
        data = static_cast<const unsigned char*>(MapViewOfFile(handle, FILE_MAP_READ, 0, 0, size));
        return data != nullptr;
    }
    ~Mapping() {
        if (data) UnmapViewOfFile(data);
        if (handle) CloseHandle(handle);
    }
};
static volatile LONG stopping = 0;
static BOOL WINAPI stop(DWORD) { InterlockedExchange(&stopping, 1); return TRUE; }

template<class T> static T field(const unsigned char* data, size_t offset) {
    T value;
    auto* bytes = reinterpret_cast<unsigned char*>(&value);
    const volatile auto* source = data + offset;
    for (size_t i = 0; i < sizeof(value); ++i) bytes[i] = source[i];
    return value;
}

static int assetto(Sender& sender) {
    Mapping physics, graphics, config;
    if (!physics.open("Local\\acpmf_physics", 24) || !graphics.open("Local\\acpmf_graphics", 8) ||
        !config.open("Local\\acpmf_static", 416)) {
        std::fprintf(stderr, "Game shared memory unavailable; use the same Proton prefix/runtime as the running game.\n");
        return 2;
    }
    std::uint32_t last = 0;
    bool seen = false;
    while (!stopping) {
        const auto before = field<std::uint32_t>(physics.data, 0);
        const auto rpm = field<std::int32_t>(physics.data, 20);
        const auto maximum = field<std::int32_t>(config.data, 412);
        const auto live = field<std::int32_t>(graphics.data, 4) == 2;
        MemoryBarrier();
        if (before == field<std::uint32_t>(physics.data, 0) && (!seen || before != last)) {
            sender.send(static_cast<float>(rpm), static_cast<float>(maximum), live);
            last = before;
            seen = true;
        }
        Sleep(10);
    }
    return 0;
}
#ifdef MOZAPROXY_LMU
static int lmu(Sender& sender) {
    Mapping mapping;
    if (!mapping.open("LMU_Data", sizeof(SharedMemoryLayout))) {
        std::fprintf(stderr, "LMU_Data unavailable. Match this helper's SDK and Proton runtime to the installed game.\n");
        return 2;
    }
    const auto* layout = reinterpret_cast<const volatile SharedMemoryLayout*>(mapping.data);
    double last = -1;
    int last_id = -1;
    while (!stopping) {
        // Only sample LED scalars. Never write LMU lock state or hold its game thread.
        // Recheck both the player selection and sampled fields before publishing.
        const auto index = layout->data.telemetry.playerVehicleIdx;
        const auto count = layout->data.telemetry.activeVehicles;
        if (layout->data.telemetry.playerHasVehicle && index < count && count <= 104) {
            const auto& source = layout->data.telemetry.telemInfo[index];
            const auto id = source.mID;
            const double elapsed = source.mElapsedTime, rpm = source.mEngineRPM, maximum = source.mEngineMaxRPM;
            const bool live = layout->data.scoring.scoringInfo.mInRealtime;
            MemoryBarrier();
            if (layout->data.telemetry.playerHasVehicle && index == layout->data.telemetry.playerVehicleIdx &&
                count == layout->data.telemetry.activeVehicles && id == source.mID && elapsed == source.mElapsedTime &&
                rpm == source.mEngineRPM && maximum == source.mEngineMaxRPM && live == layout->data.scoring.scoringInfo.mInRealtime &&
                (elapsed != last || id != last_id)) {
                sender.send(static_cast<float>(rpm), static_cast<float>(maximum), live);
                last = elapsed;
                last_id = id;
            }
        }
        Sleep(10);
    }
    return 0;
}
#endif
int main(int argc, char** argv) {
    if (argc != 3) {
        std::fprintf(stderr, "Usage: shared-memory.exe lmu|acc|ac PORT\n");
        return 2;
    }
    char* end = nullptr;
    unsigned long port = std::strtoul(argv[2], &end, 10);
    if (!end || *end || port < 1024 || port > 65535) return 2;
    unsigned char game = std::strcmp(argv[1], "lmu") == 0 ? 1 : std::strcmp(argv[1], "acc") == 0 ? 2 : std::strcmp(argv[1], "ac") == 0 ? 3 : 0;
    if (!game) return 2;
    Sender sender;
    if (!sender.open(game, static_cast<unsigned>(port))) return 2;
    SetConsoleCtrlHandler(stop, TRUE);
    if (game == 2 || game == 3) return assetto(sender);
#ifdef MOZAPROXY_LMU
    return lmu(sender);
#else
    std::fprintf(stderr, "This helper was built without the installed LMU SDK.\n");
    return 2;
#endif
}
