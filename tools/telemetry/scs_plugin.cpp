#include "packet.hpp"
#include <cstdlib>
#include <memory>
#include <scssdk_telemetry.h>
#include <common/scssdk_telemetry_common_configs.h>
#include <common/scssdk_telemetry_truck_common_channels.h>

#ifdef _WIN32
#define EXPORT
#else
#define EXPORT __attribute__((visibility("default")))
#endif

static std::unique_ptr<Sender> sender;
static float rpm = 0, maximum = 0;
static bool live = false, channel_registered = false;
static const scs_telemetry_init_params_v100_t* api = nullptr;
static unsigned registered_events = 0;
static const scs_event_t events[] = {SCS_TELEMETRY_EVENT_configuration, SCS_TELEMETRY_EVENT_started,
                                   SCS_TELEMETRY_EVENT_paused, SCS_TELEMETRY_EVENT_frame_end};

static SCSAPI_VOID channel(scs_string_t, scs_u32_t, const scs_value_t* value, scs_context_t) {
    rpm = value && value->type == SCS_VALUE_TYPE_float ? value->value_float.value : 0;
}
static SCSAPI_VOID event(scs_event_t type, const void* info, scs_context_t) {
    if (type == SCS_TELEMETRY_EVENT_configuration && info) {
        const auto* config = static_cast<const scs_telemetry_configuration_t*>(info);
        if (std::strcmp(config->id, SCS_TELEMETRY_CONFIG_truck) != 0) return;
        maximum = 0;
        for (const auto* item = config->attributes; item->name; ++item) {
            if (std::strcmp(item->name, SCS_TELEMETRY_CONFIG_ATTRIBUTE_rpm_limit) == 0 &&
                item->value.type == SCS_VALUE_TYPE_float) maximum = item->value.value_float.value;
        }
    } else if (type == SCS_TELEMETRY_EVENT_started) live = true;
    else if (type == SCS_TELEMETRY_EVENT_paused) live = false;
    if (sender && (type == SCS_TELEMETRY_EVENT_frame_end || type == SCS_TELEMETRY_EVENT_paused))
        sender->send(rpm, maximum, live);
}

extern "C" EXPORT SCSAPI_VOID scs_telemetry_shutdown() {
    if (api) {
        if (channel_registered) api->unregister_from_channel(SCS_TELEMETRY_TRUCK_CHANNEL_engine_rpm, SCS_U32_NIL, SCS_VALUE_TYPE_float);
        while (registered_events) api->unregister_from_event(events[--registered_events]);
    }
    sender.reset();
    api = nullptr;
    live = channel_registered = false;
    rpm = maximum = 0;
}
extern "C" EXPORT SCSAPI_RESULT scs_telemetry_init(scs_u32_t version, const scs_telemetry_init_params_t* params) {
    if (version != SCS_TELEMETRY_VERSION_1_00 && version != SCS_TELEMETRY_VERSION_1_01) return SCS_RESULT_unsupported;
    if (!params || api) return SCS_RESULT_invalid_parameter;
    const auto* supplied = static_cast<const scs_telemetry_init_params_v100_t*>(params);
    if (!supplied->common.game_id || std::strcmp(supplied->common.game_id, "eut2") != 0) return SCS_RESULT_unsupported;
    unsigned long port = 20777;
    if (const char* configured = std::getenv("MOZAPROXY_TELEMETRY_PORT")) {
        char* end = nullptr;
        port = std::strtoul(configured, &end, 10);
        if (!end || *end || port < 1024 || port > 65535) return SCS_RESULT_invalid_parameter;
    }
    try { sender = std::make_unique<Sender>(); }
    catch (...) { return SCS_RESULT_generic_error; }
    if (!sender->open(4, static_cast<unsigned>(port))) { sender.reset(); return SCS_RESULT_generic_error; }
    // The engine's init struct need only live for this call. Retain a copy of the callbacks.
    static scs_telemetry_init_params_v100_t callbacks;
    callbacks = *supplied;
    api = &callbacks;
    for (const auto type : events) {
        if (api->register_for_event(type, event, nullptr) != SCS_RESULT_ok) {
            scs_telemetry_shutdown();
            return SCS_RESULT_generic_error;
        }
        ++registered_events;
    }
    if (api->register_for_channel(SCS_TELEMETRY_TRUCK_CHANNEL_engine_rpm, SCS_U32_NIL, SCS_VALUE_TYPE_float,
                                  SCS_TELEMETRY_CHANNEL_FLAG_each_frame | SCS_TELEMETRY_CHANNEL_FLAG_no_value, channel, nullptr) != SCS_RESULT_ok) {
        scs_telemetry_shutdown();
        return SCS_RESULT_generic_error;
    }
    channel_registered = true;
    return SCS_RESULT_ok;
}
