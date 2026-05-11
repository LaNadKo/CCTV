class LoginResponse {
  const LoginResponse({
    required this.accessToken,
    required this.tokenType,
    required this.mustChangePassword,
    this.mediaAccessToken,
    this.mediaTokenExpiresSeconds,
  });

  final String accessToken;
  final String tokenType;
  final bool mustChangePassword;
  final String? mediaAccessToken;
  final int? mediaTokenExpiresSeconds;

  factory LoginResponse.fromJson(Map<String, dynamic> json) {
    return LoginResponse(
      accessToken: json['access_token'] as String,
      tokenType: json['token_type'] as String? ?? 'bearer',
      mustChangePassword: json['must_change_password'] as bool? ?? false,
      mediaAccessToken: json['media_access_token'] as String?,
      mediaTokenExpiresSeconds: json['media_token_expires_seconds'] as int?,
    );
  }
}

class MediaTokenResponse {
  const MediaTokenResponse({
    required this.mediaAccessToken,
    required this.expiresSeconds,
  });

  final String mediaAccessToken;
  final int expiresSeconds;

  factory MediaTokenResponse.fromJson(Map<String, dynamic> json) {
    return MediaTokenResponse(
      mediaAccessToken: json['media_access_token'] as String,
      expiresSeconds: json['media_token_expires_seconds'] as int? ?? 900,
    );
  }
}

class CurrentUser {
  const CurrentUser({
    required this.userId,
    required this.login,
    required this.roleId,
    this.firstName,
    this.lastName,
    this.middleName,
    required this.mustChangePassword,
    required this.totpEnabled,
  });

  final int userId;
  final String login;
  final int roleId;
  final String? firstName;
  final String? lastName;
  final String? middleName;
  final bool mustChangePassword;
  final bool totpEnabled;

  String get displayName {
    final parts = [lastName, firstName, middleName]
        .where((value) => value != null && value.trim().isNotEmpty)
        .cast<String>()
        .toList();
    return parts.isEmpty ? login : parts.join(' ');
  }

  String get roleLabel {
    if (roleId == 1) return 'Администратор';
    if (roleId == 2) return 'Оператор';
    return 'Смотрящий';
  }

  bool get isAdmin => roleId == 1;
  bool get canReview => roleId == 1 || roleId == 2;

  factory CurrentUser.fromJson(Map<String, dynamic> json) {
    return CurrentUser(
      userId: json['user_id'] as int,
      login: json['login'] as String,
      roleId: json['role_id'] as int,
      firstName: json['first_name'] as String?,
      lastName: json['last_name'] as String?,
      middleName: json['middle_name'] as String?,
      mustChangePassword: json['must_change_password'] as bool? ?? false,
      totpEnabled: json['totp_enabled'] as bool? ?? false,
    );
  }
}

class CameraPtzCapabilities {
  const CameraPtzCapabilities({
    required this.panTilt,
    required this.zoom,
    required this.home,
    required this.presets,
  });

  final bool panTilt;
  final bool zoom;
  final bool home;
  final bool presets;

  factory CameraPtzCapabilities.fromJson(Map<String, dynamic>? json) {
    return CameraPtzCapabilities(
      panTilt: json?['pan_tilt'] as bool? ?? false,
      zoom: json?['zoom'] as bool? ?? false,
      home: json?['home'] as bool? ?? false,
      presets: json?['presets'] as bool? ?? false,
    );
  }
}

class CameraSummary {
  const CameraSummary({
    required this.cameraId,
    required this.name,
    this.location,
    required this.permission,
    this.ipAddress,
    this.streamUrl,
    this.fps,
    required this.detectionEnabled,
    required this.recordingMode,
    this.trackingEnabled,
    this.trackingMode,
    this.groupId,
    required this.connectionKind,
    required this.onvifEnabled,
    required this.supportsPtz,
    required this.ptzCapabilities,
    required this.endpointKinds,
  });

  final int cameraId;
  final String name;
  final String? location;
  final String permission;
  final String? ipAddress;
  final String? streamUrl;
  final double? fps;
  final bool detectionEnabled;
  final String recordingMode;
  final bool? trackingEnabled;
  final String? trackingMode;
  final int? groupId;
  final String connectionKind;
  final bool onvifEnabled;
  final bool supportsPtz;
  final CameraPtzCapabilities ptzCapabilities;
  final List<String> endpointKinds;

  factory CameraSummary.fromJson(Map<String, dynamic> json) {
    return CameraSummary(
      cameraId: json['camera_id'] as int,
      name: json['name'] as String? ?? 'Camera',
      location: json['location'] as String?,
      permission: json['permission'] as String? ?? 'view',
      ipAddress: json['ip_address'] as String?,
      streamUrl: json['stream_url'] as String?,
      fps: (json['fps'] as num?)?.toDouble(),
      detectionEnabled: json['detection_enabled'] as bool? ?? false,
      recordingMode: json['recording_mode'] as String? ?? 'off',
      trackingEnabled: json['tracking_enabled'] as bool?,
      trackingMode: json['tracking_mode'] as String?,
      groupId: json['group_id'] as int?,
      connectionKind: json['connection_kind'] as String? ?? 'manual',
      onvifEnabled: json['onvif_enabled'] as bool? ?? false,
      supportsPtz: json['supports_ptz'] as bool? ?? false,
      ptzCapabilities: CameraPtzCapabilities.fromJson(
        json['ptz_capabilities'] as Map<String, dynamic>?,
      ),
      endpointKinds: (json['endpoint_kinds'] as List<dynamic>? ?? const [])
          .map((value) => '$value')
          .toList(),
    );
  }
}

class AssignedCameraInfo {
  const AssignedCameraInfo({
    required this.cameraId,
    required this.name,
    this.location,
  });

  final int cameraId;
  final String name;
  final String? location;

  factory AssignedCameraInfo.fromJson(Map<String, dynamic> json) {
    return AssignedCameraInfo(
      cameraId: json['camera_id'] as int,
      name: json['name'] as String? ?? 'Camera',
      location: json['location'] as String?,
    );
  }
}

class ProcessorOut {
  const ProcessorOut({
    required this.processorId,
    required this.name,
    required this.status,
    this.host,
    this.lastHeartbeatAt,
    required this.assignedCameras,
    this.cameraCount = 0,
    this.metrics,
    this.pendingCommands = 0,
    this.runningCommands = 0,
    this.lastCommand,
  });

  final int processorId;
  final String name;
  final String status;
  final String? host;
  final DateTime? lastHeartbeatAt;
  final List<AssignedCameraInfo> assignedCameras;
  final int cameraCount;
  final Map<String, dynamic>? metrics;
  final int pendingCommands;
  final int runningCommands;
  final Map<String, dynamic>? lastCommand;

  bool get online => status.toLowerCase() == 'online';

  factory ProcessorOut.fromJson(Map<String, dynamic> json) {
    return ProcessorOut(
      processorId: json['processor_id'] as int,
      name: json['name'] as String? ?? 'Processor',
      status: json['status'] as String? ?? 'offline',
      host: json['host'] as String? ?? json['ip_address'] as String?,
      lastHeartbeatAt: DateTime.tryParse(
        '${json['last_heartbeat_at'] ?? json['last_heartbeat'] ?? ''}',
      ),
      assignedCameras: (json['assigned_cameras'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(AssignedCameraInfo.fromJson)
          .toList(),
      cameraCount: (json['camera_count'] as num?)?.toInt() ?? 0,
      metrics: json['metrics'] is Map
          ? (json['metrics'] as Map).map(
              (key, value) => MapEntry('$key', value),
            )
          : null,
      pendingCommands: (json['pending_commands'] as num?)?.toInt() ?? 0,
      runningCommands: (json['running_commands'] as num?)?.toInt() ?? 0,
      lastCommand: json['last_command'] is Map
          ? (json['last_command'] as Map).map(
              (key, value) => MapEntry('$key', value),
            )
          : null,
    );
  }
}

class PendingEvent {
  const PendingEvent({
    required this.eventId,
    required this.cameraId,
    this.cameraName,
    this.personLabel,
    this.confidence,
    required this.eventTs,
  });

  final int eventId;
  final int cameraId;
  final String? cameraName;
  final String? personLabel;
  final double? confidence;
  final DateTime eventTs;

  factory PendingEvent.fromJson(Map<String, dynamic> json) {
    return PendingEvent(
      eventId: json['event_id'] as int,
      cameraId: json['camera_id'] as int,
      cameraName: json['camera_name'] as String?,
      personLabel: json['person_label'] as String?,
      confidence: (json['confidence'] as num?)?.toDouble(),
      eventTs: DateTime.tryParse('${json['event_ts']}') ?? DateTime.now(),
    );
  }
}
