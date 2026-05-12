import 'package:flutter/services.dart';

const int humanNameMaxLength = 48;

final RegExp _humanNamePattern = RegExp(
  r"^[A-Za-zА-Яа-яЁё]+(?:[ '\-][A-Za-zА-Яа-яЁё]+)*$",
);

List<TextInputFormatter> humanNameInputFormatters() {
  return [
    FilteringTextInputFormatter.allow(RegExp(r"[A-Za-zА-Яа-яЁё\s'\-]")),
    LengthLimitingTextInputFormatter(humanNameMaxLength),
  ];
}

String normalizeHumanName(String value) {
  return value.trim().replaceAll(RegExp(r'\s+'), ' ');
}

String? validateOptionalHumanName(String label, String value) {
  final normalized = normalizeHumanName(value);
  if (normalized.isEmpty) return null;
  if (normalized.length > humanNameMaxLength) {
    return '$label: максимум $humanNameMaxLength символов';
  }
  if (!_humanNamePattern.hasMatch(normalized)) {
    return '$label: только буквы, пробел, дефис или апостроф';
  }
  return null;
}
