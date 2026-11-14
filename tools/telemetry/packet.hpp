#pragma once
#include <cstdint>
#include <chrono>
#include <cmath>
#include <cstring>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <windows.h>
#else
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

// Versioned, little-endian loopback protocol. Game IDs: LMU1, ACC2, AC3, ETS2 4.
#pragma pack(push, 1)
struct Packet {
    char magic[4] = {'M','Z','T','P'};
    std::uint8_t version = 1, game = 0;
    std::uint16_t flags = 0;
    std::uint32_t session = 0, sequence = 0;
    float rpm = 0, maximum = 0;
};
#pragma pack(pop)
static_assert(sizeof(Packet) == 24, "Telemetry wire layout changed");

enum PacketFlags : std::uint16_t {
    Racing = 1, Yellow = 2, Blue = 4, Limiter = 8, ABS = 16, TC = 32,
    ScoringKnown = 64, AssistanceKnown = 128
};

class Sender {
#ifdef _WIN32
    SOCKET socket_ = INVALID_SOCKET;
    bool winsock_ = false;
#else
    int socket_ = -1;
#endif
    sockaddr_in destination_{};
    Packet packet_;
    std::chrono::steady_clock::time_point last_{};
public:
    bool open(std::uint8_t game, unsigned port) {
        if (port < 1024 || port > 65535) return false;
#ifdef _WIN32
        WSADATA data{};
        if (WSAStartup(MAKEWORD(2,2), &data)) return false;
        winsock_ = true;
#endif
        socket_ = ::socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
#ifdef _WIN32
        if (socket_ == INVALID_SOCKET) return false;
#else
        if (socket_ < 0) return false;
#endif
        destination_.sin_family = AF_INET;
        destination_.sin_port = htons(static_cast<std::uint16_t>(port));
        destination_.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        packet_.game = game;
        packet_.session = static_cast<std::uint32_t>(std::chrono::steady_clock::now().time_since_epoch().count());
        return true;
    }
    void reset_session() {
        ++packet_.session;
        packet_.sequence = 0;
        last_ = {};
    }
    bool send(float rpm, float maximum, bool live, std::uint16_t flags = 0) {
        if (!std::isfinite(rpm) || !std::isfinite(maximum) || rpm < 0 || rpm > 100000 || maximum <= 0 || maximum > 100000) return false;
        const auto now = std::chrono::steady_clock::now();
        if (now - last_ < std::chrono::milliseconds(50) && (live || !(packet_.flags & Racing))) return false;
        last_ = now;
        packet_.flags = static_cast<std::uint16_t>((flags & ~Racing) | (live ? Racing : 0));
        packet_.sequence++;
        packet_.rpm = rpm;
        packet_.maximum = maximum;
        return sendto(socket_, reinterpret_cast<const char*>(&packet_), sizeof(packet_), 0,
                      reinterpret_cast<const sockaddr*>(&destination_), sizeof(destination_)) == static_cast<int>(sizeof(packet_));
    }
    ~Sender() {
#ifdef _WIN32
        if (socket_ != INVALID_SOCKET) closesocket(socket_);
        if (winsock_) WSACleanup();
#else
        if (socket_ >= 0) close(socket_);
#endif
    }
};
