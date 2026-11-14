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

struct Lease {
    const char* path = nullptr;
    ULONGLONG checked = 0;
    bool valid = true;
    bool alive() {
        if (!path) return true;
        const auto tick = GetTickCount64();
        if (checked && tick - checked < 500) return valid;
        checked = tick;
        WIN32_FILE_ATTRIBUTE_DATA attributes{};
        if (!GetFileAttributesExA(path, GetFileExInfoStandard, &attributes) ||
            (attributes.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) return valid = false;
        FILETIME current;
        GetSystemTimeAsFileTime(&current);
        const auto ticks = [](const FILETIME& time) {
            return (static_cast<ULONGLONG>(time.dwHighDateTime) << 32) | time.dwLowDateTime;
        };
        const auto now = ticks(current), written = ticks(attributes.ftLastWriteTime);
        return valid = written <= now && now - written <= 10ULL * 10000000;
    }
};

template<class T> static T field(const unsigned char* data, size_t offset) {
    T value;
    auto* bytes = reinterpret_cast<unsigned char*>(&value);
    const volatile auto* source = data + offset;
    for (size_t i = 0; i < sizeof(value); ++i) bytes[i] = source[i];
    return value;
}

static int assetto(Sender& sender, Lease& lease) {
    Mapping physics, graphics, config;
    if (!physics.open("Local\\acpmf_physics", 24) || !graphics.open("Local\\acpmf_graphics", 8) ||
        !config.open("Local\\acpmf_static", 416)) {
        std::fprintf(stderr, "Game shared memory unavailable; use the same Proton prefix/runtime as the running game.\n");
        return 2;
    }
    std::uint32_t last = 0;
    bool seen = false;
    while (!stopping && lease.alive()) {
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
static int lmu(Sender& sender, Lease& lease) {
    Mapping mapping;
    if (!mapping.open("LMU_Data", sizeof(SharedMemoryLayout))) {
        std::fprintf(stderr, "LMU_Data unavailable. Match this helper's SDK and Proton runtime to the installed game.\n");
        return 2;
    }
    const auto* layout = reinterpret_cast<const volatile SharedMemoryLayout*>(mapping.data);
    double last = -1;
    int last_id = -1;
    long last_session = -1;
    double score_elapsed = -1;
    bool score_progressed = false, last_live = false;
    float last_rpm = 0, last_maximum = 0;
    auto score_updated = std::chrono::steady_clock::now();
    while (!stopping && lease.alive()) {
        // Rechecks are best effort; never write LMU's lock or hold its game thread.
        const auto index = layout->data.telemetry.playerVehicleIdx;
        const auto count = layout->data.telemetry.activeVehicles;
        const bool has_vehicle = layout->data.telemetry.playerHasVehicle;
        const auto& scoring = layout->data.scoring.scoringInfo;
        const bool realtime = scoring.mInRealtime;
        const auto phase = scoring.mGamePhase;
        const bool live = has_vehicle && realtime && phase != 9;
        MemoryBarrier();
        if (!live && last_live && has_vehicle == layout->data.telemetry.playerHasVehicle &&
            realtime == scoring.mInRealtime && phase == scoring.mGamePhase &&
            sender.send(last_rpm, last_maximum, false)) last_live = false;
        if (has_vehicle && index < count && count <= 104) {
            const auto& source = layout->data.telemetry.telemInfo[index];
            const auto id = source.mID;
            const double elapsed = source.mElapsedTime, rpm = source.mEngineRPM, maximum = source.mEngineMaxRPM;
            const auto limiter = source.mSpeedLimiter;
            const bool abs = source.mABSActive, tc = source.mTCActive;
            const auto session = scoring.mSession;
            const double score_time = scoring.mCurrentET;
            const auto vehicles = scoring.mNumVehicles;
            const volatile VehicleScoringInfoV01* player = nullptr;
            if (vehicles > 0 && vehicles <= 104) {
                for (long i = 0; i < vehicles; ++i) {
                    const auto& candidate = layout->data.scoring.vehScoringInfo[i];
                    if (candidate.mID == id && candidate.mIsPlayer) {
                        player = &candidate;
                        break;
                    }
                }
            }
            const auto flag = player ? player->mFlag : 255;
            const auto individual_phase = player ? player->mIndividualPhase : 255;
            const bool yellow = player && player->mUnderYellow;
            MemoryBarrier();
            if (layout->data.telemetry.playerHasVehicle && index == layout->data.telemetry.playerVehicleIdx &&
                count == layout->data.telemetry.activeVehicles && id == source.mID && elapsed == source.mElapsedTime &&
                rpm == source.mEngineRPM && maximum == source.mEngineMaxRPM && realtime == scoring.mInRealtime &&
                phase == scoring.mGamePhase && session == scoring.mSession && std::isfinite(elapsed)) {
                if (id != last_id || session != last_session || elapsed < last) {
                    if (last_id != -1) sender.reset_session();
                    last_id = id;
                    last_session = session;
                    last = -1;
                    score_elapsed = -1;
                    score_progressed = false;
                }
                const auto now = std::chrono::steady_clock::now();
                const bool score_stable = player && score_time == scoring.mCurrentET && vehicles == scoring.mNumVehicles &&
                    id == player->mID && player->mIsPlayer && flag == player->mFlag &&
                    individual_phase == player->mIndividualPhase && yellow == player->mUnderYellow && std::isfinite(score_time);
                if (score_stable && score_time != score_elapsed) {
                    score_progressed = score_elapsed >= 0 && score_time > score_elapsed;
                    score_elapsed = score_time;
                    score_updated = now;
                }
                std::uint16_t flags = 0;
                if (live && score_stable && score_progressed && now - score_updated <= std::chrono::milliseconds(500) &&
                    (flag == 0 || flag == 6) && individual_phase <= 11) {
                    flags |= ScoringKnown;
                    if (yellow || individual_phase == 10) flags |= Yellow;
                    if (flag == 6) flags |= Blue;
                }
                if (live && limiter <= 1 && limiter == source.mSpeedLimiter && abs == source.mABSActive && tc == source.mTCActive) {
                    flags |= AssistanceKnown;
                    if (limiter) flags |= Limiter;
                    if (abs) flags |= ABS;
                    if (tc) flags |= TC;
                }
                if (((live && elapsed != last) || live != last_live || last < 0) &&
                    sender.send(static_cast<float>(rpm), static_cast<float>(maximum), live, flags)) {
                    last = elapsed;
                    last_live = live;
                    last_rpm = static_cast<float>(rpm);
                    last_maximum = static_cast<float>(maximum);
                }
            }
        }
        Sleep(10);
    }
    return 0;
}
#endif
int main(int argc, char** argv) {
    if (argc != 3 && argc != 4) {
        std::fprintf(stderr, "Usage: shared-memory.exe lmu|acc|ac PORT [ABSOLUTE_WINDOWS_LEASE_PATH]\n");
        return 2;
    }
    char* end = nullptr;
    unsigned long port = std::strtoul(argv[2], &end, 10);
    if (!end || *end || port < 1024 || port > 65535) return 2;
    unsigned char game = std::strcmp(argv[1], "lmu") == 0 ? 1 : std::strcmp(argv[1], "acc") == 0 ? 2 : std::strcmp(argv[1], "ac") == 0 ? 3 : 0;
    if (!game) return 2;
    Lease lease;
    if (argc == 4) {
        const auto length = std::strlen(argv[3]);
        const bool drive = length >= 3 && ((argv[3][0] >= 'A' && argv[3][0] <= 'Z') ||
            (argv[3][0] >= 'a' && argv[3][0] <= 'z')) && argv[3][1] == ':' &&
            (argv[3][2] == '\\' || argv[3][2] == '/');
        if (!drive && !(length > 2 && argv[3][0] == '\\' && argv[3][1] == '\\')) return 2;
        lease.path = argv[3];
        if (!lease.alive()) return 0;
    }
    Sender sender;
    if (!sender.open(game, static_cast<unsigned>(port))) return 2;
    SetConsoleCtrlHandler(stop, TRUE);
    if (game == 2 || game == 3) return assetto(sender, lease);
#ifdef MOZAPROXY_LMU
    return lmu(sender, lease);
#else
    std::fprintf(stderr, "This helper was built without the installed LMU SDK.\n");
    return 2;
#endif
}
