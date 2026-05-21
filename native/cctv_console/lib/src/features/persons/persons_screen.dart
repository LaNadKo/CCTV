import 'dart:async';

import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/models/models.dart';
import '../../core/network/api_client.dart';
import '../../core/theme/app_theme.dart';
import '../../shared/widgets/glass_panel.dart';
import '../auth/auth_controller.dart';

class PersonsManagementScreen extends StatefulWidget {
  const PersonsManagementScreen({super.key});

  @override
  State<PersonsManagementScreen> createState() =>
      _PersonsManagementScreenState();
}

class _PersonsManagementScreenState extends State<PersonsManagementScreen> {
  final _searchController = TextEditingController();
  final _createFirstName = TextEditingController();
  final _createLastName = TextEditingController();
  final _createMiddleName = TextEditingController();
  final _editFirstName = TextEditingController();
  final _editLastName = TextEditingController();
  final _editMiddleName = TextEditingController();

  bool _busy = false;
  String? _error;
  int? _selectedPersonId;
  int? _embeddingCameraId;
  List<Map<String, dynamic>> _persons = const [];
  List<CameraSummary> _cameras = const [];
  List<Map<String, dynamic>> _appearances = const [];

  @override
  void initState() {
    super.initState();
    _searchController.addListener(() => setState(() {}));
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void dispose() {
    _searchController.dispose();
    _createFirstName.dispose();
    _createLastName.dispose();
    _createMiddleName.dispose();
    _editFirstName.dispose();
    _editLastName.dispose();
    _editMiddleName.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    await _run(() async {
      final (api, token) = _deps();
      final result = await Future.wait([
        api.getJsonList('/persons', token: token),
        api.listCameras(token),
      ]);
      final persons = result[0] as List<Map<String, dynamic>>;
      final cameras = result[1] as List<CameraSummary>;
      final selectedId = _resolveSelectedPersonId(persons);
      final appearances = await _fetchAppearances(selectedId);
      setState(() {
        _persons = persons;
        _cameras = cameras;
        _selectedPersonId = selectedId;
        _appearances = appearances;
        if (_embeddingCameraId != null &&
            !_cameras.any((camera) => camera.cameraId == _embeddingCameraId)) {
          _embeddingCameraId = null;
        }
      });
      _syncEditControllers();
    });
  }

  Future<void> _createPerson() async {
    await _run(() async {
      final (api, token) = _deps();
      final created = await api.postJson(
        '/persons',
        token: token,
        body: {
          'first_name': _optional(_createFirstName.text),
          'last_name': _optional(_createLastName.text),
          'middle_name': _optional(_createMiddleName.text),
        },
      );
      _createFirstName.clear();
      _createLastName.clear();
      _createMiddleName.clear();
      _selectedPersonId = created['person_id'] as int?;
      await _reloadQuietly();
      _toast('Персона создана');
    });
  }

  Future<void> _saveSelectedPerson() async {
    final personId = _selectedPersonId;
    if (personId == null) return;
    await _run(() async {
      final (api, token) = _deps();
      await api.patchJson(
        '/persons/$personId',
        token: token,
        body: {
          'first_name': _editFirstName.text.trim(),
          'last_name': _editLastName.text.trim(),
          'middle_name': _editMiddleName.text.trim(),
        },
      );
      await _reloadQuietly();
      _toast('Карточка персоны сохранена');
    });
  }

  Future<void> _deleteSelectedPerson() async {
    final personId = _selectedPersonId;
    if (personId == null) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Удалить персону?'),
        content: Text(
          'Персона ${_selectedLabel()} будет скрыта из списка и отвязана от камер.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Удалить'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await _run(() async {
      final (api, token) = _deps();
      await api.deleteVoid('/persons/$personId', token: token);
      _selectedPersonId = null;
      await _reloadQuietly();
      _toast('Персона удалена');
    });
  }

  Future<void> _addPhotoEmbedding() async {
    final personId = _selectedPersonId;
    if (personId == null) return;
    final picked = await openFile(
      acceptedTypeGroups: const [
        XTypeGroup(
          label: 'Изображения',
          extensions: ['jpg', 'jpeg', 'png', 'webp'],
          mimeTypes: ['image/jpeg', 'image/png', 'image/webp'],
        ),
      ],
    );
    if (picked == null) return;
    await _run(() async {
      final (api, token) = _deps();
      final result = await api.uploadPersonPhotoStream(
        token,
        personId,
        stream: picked.openRead(),
        length: await picked.length(),
        filename: picked.name,
        cameraId: _embeddingCameraId,
      );
      await _reloadQuietly();
      final status = '${result['status'] ?? 'added'}';
      final similarity = result['max_similarity'];
      _toast(
        status == 'added'
            ? 'Фото добавлено в эмбеддинги'
            : 'Backend вернул статус $status'
                  '${similarity == null ? '' : ', similarity $similarity'}',
      );
    });
  }

  Future<void> _captureLiveEmbedding() async {
    final personId = _selectedPersonId;
    final cameraId = _embeddingCameraId;
    if (personId == null) return;
    if (cameraId == null) {
      _toast('Выберите камеру для live-кадра');
      return;
    }
    await _run(() async {
      final (api, token) = _deps();
      final bytes = await api.captureCameraJpegFrame(token, cameraId);
      final result = await api.uploadPersonPhotoStream(
        token,
        personId,
        stream: Stream<List<int>>.value(bytes),
        length: bytes.length,
        filename: 'live-camera-$cameraId.jpg',
        cameraId: cameraId,
      );
      await _reloadQuietly();
      _toast('Live-кадр отправлен: ${result['status'] ?? 'ok'}');
    });
  }

  Future<void> _createPersonFromPhoto() async {
    final picked = await openFile(
      acceptedTypeGroups: const [
        XTypeGroup(
          label: 'Изображения',
          extensions: ['jpg', 'jpeg', 'png', 'webp'],
          mimeTypes: ['image/jpeg', 'image/png', 'image/webp'],
        ),
      ],
    );
    if (picked == null) return;
    await _run(() async {
      final (api, token) = _deps();
      final result = await api.enrollPersonPhotoStream(
        token,
        stream: picked.openRead(),
        length: await picked.length(),
        filename: picked.name,
        firstName: _createFirstName.text,
        lastName: _createLastName.text,
        middleName: _createMiddleName.text,
      );
      _createFirstName.clear();
      _createLastName.clear();
      _createMiddleName.clear();
      _selectedPersonId = result['person_id'] as int?;
      await _reloadQuietly();
      _toast('Персона создана из фото');
    });
  }

  Future<void> _reloadQuietly() async {
    final (api, token) = _deps();
    final result = await Future.wait([
      api.getJsonList('/persons', token: token),
      api.listCameras(token),
    ]);
    if (!mounted) return;
    final persons = result[0] as List<Map<String, dynamic>>;
    final cameras = result[1] as List<CameraSummary>;
    final selectedId = _resolveSelectedPersonId(persons);
    final appearances = await _fetchAppearances(selectedId);
    setState(() {
      _persons = persons;
      _cameras = cameras;
      _selectedPersonId = selectedId;
      _appearances = appearances;
    });
    _syncEditControllers();
  }

  Future<List<Map<String, dynamic>>> _fetchAppearances(int? personId) async {
    if (personId == null) return const [];
    final (api, token) = _deps();
    final result = await api.getJson(
      '/reports/appearances',
      token: token,
      query: {'person_id': '$personId'},
    );
    final map = result is Map
        ? result.map((key, value) => MapEntry('$key', value))
        : <String, dynamic>{};
    final items = map['items'];
    if (items is! List) return const [];
    return items
        .whereType<Map>()
        .map((item) => item.map((key, value) => MapEntry('$key', value)))
        .toList();
  }

  Future<void> _loadSelectedAppearances() async {
    try {
      final appearances = await _fetchAppearances(_selectedPersonId);
      if (mounted) setState(() => _appearances = appearances);
    } catch (_) {
      if (mounted) setState(() => _appearances = const []);
    }
  }

  (ApiClient, String) _deps() {
    final auth = context.read<AuthController>();
    final token = auth.accessToken;
    if (token == null) throw ApiException('Нет активной сессии');
    return (auth.apiClient, token);
  }

  Future<void> _run(Future<void> Function() action) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  int? _resolveSelectedPersonId(List<Map<String, dynamic>> persons) {
    if (persons.isEmpty) return null;
    if (_selectedPersonId != null &&
        persons.any((person) => person['person_id'] == _selectedPersonId)) {
      return _selectedPersonId;
    }
    return persons.first['person_id'] as int?;
  }

  void _selectPerson(int personId) {
    setState(() => _selectedPersonId = personId);
    _syncEditControllers();
    unawaited(_loadSelectedAppearances());
  }

  void _syncEditControllers() {
    final person = _selectedPerson();
    _editFirstName.text = '${person?['first_name'] ?? ''}';
    _editLastName.text = '${person?['last_name'] ?? ''}';
    _editMiddleName.text = '${person?['middle_name'] ?? ''}';
  }

  Map<String, dynamic>? _selectedPerson() {
    final personId = _selectedPersonId;
    if (personId == null) return null;
    for (final person in _persons) {
      if (person['person_id'] == personId) return person;
    }
    return null;
  }

  List<Map<String, dynamic>> get _filteredPersons {
    final query = _searchController.text.trim().toLowerCase();
    if (query.isEmpty) return _persons;
    return _persons.where((person) {
      final label = _personLabel(person).toLowerCase();
      return label.contains(query) || '${person['person_id']}'.contains(query);
    }).toList();
  }

  int get _embeddingsCount => _persons.fold<int>(
    0,
    (sum, person) => sum + ((person['embeddings_count'] as num?)?.toInt() ?? 0),
  );

  String _selectedLabel() {
    final person = _selectedPerson();
    return person == null ? 'не выбрана' : _personLabel(person);
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), behavior: SnackBarBehavior.floating),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final filtered = _filteredPersons;
    final selected = _selectedPerson();

    return RefreshIndicator(
      onRefresh: _load,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(),
        slivers: [
          SliverToBoxAdapter(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Персоны',
                            style: Theme.of(context).textTheme.headlineMedium
                                ?.copyWith(
                                  color: colors.textStrong,
                                  fontWeight: FontWeight.w900,
                                ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            'Карточки людей и эмбеддинги для распознавания по камерам.',
                            style: TextStyle(color: colors.muted, fontSize: 13),
                          ),
                        ],
                      ),
                    ),
                    IconButton.filledTonal(
                      onPressed: _busy ? null : _load,
                      icon: _busy
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.refresh_rounded),
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                if (_error != null) ...[
                  _InlineError(message: _error!),
                  const SizedBox(height: 12),
                ],
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    _Metric(
                      label: 'Персон',
                      value: '${_persons.length}',
                      icon: Icons.badge_rounded,
                    ),
                    _Metric(
                      label: 'В выборке',
                      value: '${filtered.length}',
                      icon: Icons.search_rounded,
                    ),
                    _Metric(
                      label: 'Эмбеддингов',
                      value: '$_embeddingsCount',
                      icon: Icons.data_object_rounded,
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final narrow = constraints.maxWidth < 960;
                    final list = _PersonsListPanel(
                      persons: filtered,
                      selectedPersonId: _selectedPersonId,
                      searchController: _searchController,
                      onSelect: _selectPerson,
                    );
                    final detail = _PersonDetailPanel(
                      person: selected,
                      busy: _busy,
                      firstName: _editFirstName,
                      lastName: _editLastName,
                      middleName: _editMiddleName,
                      createFirstName: _createFirstName,
                      createLastName: _createLastName,
                      createMiddleName: _createMiddleName,
                      cameras: _cameras,
                      embeddingCameraId: _embeddingCameraId,
                      onEmbeddingCameraChanged: (value) =>
                          setState(() => _embeddingCameraId = value),
                      onCreate: _createPerson,
                      onCreateFromPhoto: _createPersonFromPhoto,
                      onSave: _saveSelectedPerson,
                      onDelete: _deleteSelectedPerson,
                      onAddPhoto: _addPhotoEmbedding,
                      onCaptureLive: _captureLiveEmbedding,
                      appearances: _appearances,
                    );
                    if (narrow) {
                      return Column(
                        children: [list, const SizedBox(height: 14), detail],
                      );
                    }
                    return Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(width: 390, child: list),
                        const SizedBox(width: 14),
                        Expanded(child: detail),
                      ],
                    );
                  },
                ),
                const SizedBox(height: 24),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _PersonsListPanel extends StatelessWidget {
  const _PersonsListPanel({
    required this.persons,
    required this.selectedPersonId,
    required this.searchController,
    required this.onSelect,
  });

  final List<Map<String, dynamic>> persons;
  final int? selectedPersonId;
  final TextEditingController searchController;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return GlassPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Список персон',
            style: TextStyle(
              color: colors.textStrong,
              fontSize: 16,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: searchController,
            decoration: const InputDecoration(
              prefixIcon: Icon(Icons.search_rounded),
              labelText: 'Поиск по ФИО или ID',
            ),
          ),
          const SizedBox(height: 12),
          SizedBox(
            height: 520,
            child: persons.isEmpty
                ? const _EmptyState(text: 'Персоны не найдены')
                : ListView.builder(
                    itemCount: persons.length,
                    itemExtent: 82,
                    itemBuilder: (context, index) {
                      final person = persons[index];
                      final id = person['person_id'] as int;
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: _PersonListTile(
                          person: person,
                          selected: id == selectedPersonId,
                          onTap: () => onSelect(id),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}

class _PersonListTile extends StatelessWidget {
  const _PersonListTile({
    required this.person,
    required this.selected,
    required this.onTap,
  });

  final Map<String, dynamic> person;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final embeddings = (person['embeddings_count'] as num?)?.toInt() ?? 0;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 160),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        gradient: selected
            ? LinearGradient(
                colors: [
                  colors.primaryAccent.withValues(alpha: 0.22),
                  colors.secondaryAccent.withValues(alpha: 0.18),
                ],
              )
            : null,
        color: selected ? null : colors.surfaceMuted,
        border: Border.all(
          color: selected ? colors.primaryAccent : colors.border,
        ),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          child: Row(
            children: [
              CircleAvatar(
                radius: 20,
                backgroundColor: colors.primaryAccent.withValues(alpha: 0.16),
                child: Text(
                  '${person['person_id']}',
                  style: TextStyle(
                    color: colors.textStrong,
                    fontSize: 12,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(
                      _personLabel(person),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: colors.textStrong,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Эмбеддингов: $embeddings',
                      style: TextStyle(color: colors.muted, fontSize: 12),
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right_rounded, color: colors.muted),
            ],
          ),
        ),
      ),
    );
  }
}

class _PersonDetailPanel extends StatelessWidget {
  const _PersonDetailPanel({
    required this.person,
    required this.busy,
    required this.firstName,
    required this.lastName,
    required this.middleName,
    required this.createFirstName,
    required this.createLastName,
    required this.createMiddleName,
    required this.cameras,
    required this.embeddingCameraId,
    required this.onEmbeddingCameraChanged,
    required this.onCreate,
    required this.onCreateFromPhoto,
    required this.onSave,
    required this.onDelete,
    required this.onAddPhoto,
    required this.onCaptureLive,
    required this.appearances,
  });

  final Map<String, dynamic>? person;
  final bool busy;
  final TextEditingController firstName;
  final TextEditingController lastName;
  final TextEditingController middleName;
  final TextEditingController createFirstName;
  final TextEditingController createLastName;
  final TextEditingController createMiddleName;
  final List<CameraSummary> cameras;
  final int? embeddingCameraId;
  final ValueChanged<int?> onEmbeddingCameraChanged;
  final VoidCallback onCreate;
  final VoidCallback onCreateFromPhoto;
  final VoidCallback onSave;
  final VoidCallback onDelete;
  final VoidCallback onAddPhoto;
  final VoidCallback onCaptureLive;
  final List<Map<String, dynamic>> appearances;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Column(
      children: [
        GlassPanel(
          padding: const EdgeInsets.all(16),
          child: person == null
              ? const _EmptyState(text: 'Выберите персону из списка')
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                _personLabel(person!),
                                style: TextStyle(
                                  color: colors.textStrong,
                                  fontSize: 18,
                                  fontWeight: FontWeight.w900,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                'ID ${person!['person_id']} · эмбеддингов: ${person!['embeddings_count'] ?? 0}',
                                style: TextStyle(
                                  color: colors.muted,
                                  fontSize: 12,
                                ),
                              ),
                            ],
                          ),
                        ),
                        IconButton(
                          tooltip: 'Удалить персону',
                          onPressed: busy ? null : onDelete,
                          icon: Icon(
                            Icons.delete_rounded,
                            color: colors.danger,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    _NameFields(
                      firstName: firstName,
                      lastName: lastName,
                      middleName: middleName,
                    ),
                    const SizedBox(height: 14),
                    Row(
                      children: [
                        ElevatedButton.icon(
                          onPressed: busy ? null : onSave,
                          icon: const Icon(Icons.save_rounded, size: 18),
                          label: const Text('Сохранить'),
                        ),
                        const SizedBox(width: 10),
                        OutlinedButton.icon(
                          onPressed: busy ? null : onAddPhoto,
                          icon: const Icon(Icons.add_photo_alternate_rounded),
                          label: const Text('Добавить фото'),
                        ),
                        const SizedBox(width: 10),
                        OutlinedButton.icon(
                          onPressed: busy ? null : onCaptureLive,
                          icon: const Icon(Icons.camera_rounded),
                          label: const Text('Кадр из Live'),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    _CameraSelector(
                      cameras: cameras,
                      value: embeddingCameraId,
                      onChanged: onEmbeddingCameraChanged,
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'Фото используется для добавления эмбеддинга. Если локальное извлечение лица недоступно, backend попробует Processor выбранной камеры.',
                      style: TextStyle(color: colors.muted, fontSize: 12),
                    ),
                    const SizedBox(height: 14),
                    _AppearancesPanel(items: appearances),
                  ],
                ),
        ),
        const SizedBox(height: 14),
        GlassPanel(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Новая персона',
                style: TextStyle(
                  color: colors.textStrong,
                  fontSize: 16,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 12),
              _NameFields(
                firstName: createFirstName,
                lastName: createLastName,
                middleName: createMiddleName,
              ),
              const SizedBox(height: 14),
              ElevatedButton.icon(
                onPressed: busy ? null : onCreate,
                icon: const Icon(Icons.person_add_alt_1_rounded, size: 18),
                label: const Text('Создать персону'),
              ),
              const SizedBox(height: 10),
              OutlinedButton.icon(
                onPressed: busy ? null : onCreateFromPhoto,
                icon: const Icon(Icons.add_a_photo_rounded, size: 18),
                label: const Text('Создать из фото'),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _AppearancesPanel extends StatelessWidget {
  const _AppearancesPanel({required this.items});

  final List<Map<String, dynamic>> items;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'История появлений',
            style: TextStyle(
              color: colors.textStrong,
              fontSize: 15,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 10),
          if (items.isEmpty)
            Text('Появлений пока нет.', style: TextStyle(color: colors.muted))
          else
            for (final item in items.take(10))
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(
                  children: [
                    Icon(
                      Icons.visibility_rounded,
                      color: colors.primaryAccent,
                      size: 18,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        '${item['camera_name'] ?? 'Камера #${item['camera_id']}'} · ${item['event_ts'] ?? '-'} · confidence ${item['confidence'] ?? '-'}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(color: colors.text, fontSize: 12),
                      ),
                    ),
                  ],
                ),
              ),
        ],
      ),
    );
  }
}

class _NameFields extends StatelessWidget {
  const _NameFields({
    required this.firstName,
    required this.lastName,
    required this.middleName,
  });

  final TextEditingController firstName;
  final TextEditingController lastName;
  final TextEditingController middleName;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final narrow = constraints.maxWidth < 720;
        final fields = [
          TextField(
            controller: lastName,
            decoration: const InputDecoration(labelText: 'Фамилия'),
          ),
          TextField(
            controller: firstName,
            decoration: const InputDecoration(labelText: 'Имя'),
          ),
          TextField(
            controller: middleName,
            decoration: const InputDecoration(labelText: 'Отчество'),
          ),
        ];
        if (narrow) {
          return Column(
            children: [
              for (final field in fields) ...[
                field,
                if (field != fields.last) const SizedBox(height: 10),
              ],
            ],
          );
        }
        return Row(
          children: [
            for (var index = 0; index < fields.length; index++) ...[
              Expanded(child: fields[index]),
              if (index != fields.length - 1) const SizedBox(width: 10),
            ],
          ],
        );
      },
    );
  }
}

class _CameraSelector extends StatelessWidget {
  const _CameraSelector({
    required this.cameras,
    required this.value,
    required this.onChanged,
  });

  final List<CameraSummary> cameras;
  final int? value;
  final ValueChanged<int?> onChanged;

  @override
  Widget build(BuildContext context) {
    return DropdownButtonFormField<int?>(
      initialValue: value,
      decoration: const InputDecoration(
        labelText: 'Камера для fallback через Processor',
      ),
      items: [
        const DropdownMenuItem<int?>(
          value: null,
          child: Text('Не использовать fallback'),
        ),
        for (final camera in cameras)
          DropdownMenuItem<int?>(
            value: camera.cameraId,
            child: Text(camera.name),
          ),
      ],
      onChanged: onChanged,
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value, required this.icon});

  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      width: 178,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        color: colors.surfaceMuted,
        border: Border.all(color: colors.border),
      ),
      child: Row(
        children: [
          Icon(icon, color: colors.primaryAccent, size: 20),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: TextStyle(color: colors.muted, fontSize: 12),
                ),
                Text(
                  value,
                  style: TextStyle(
                    color: colors.textStrong,
                    fontSize: 22,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Center(
      child: Text(
        text,
        style: TextStyle(color: colors.muted, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class _InlineError extends StatelessWidget {
  const _InlineError({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        color: colors.danger.withValues(alpha: 0.1),
        border: Border.all(color: colors.danger.withValues(alpha: 0.25)),
      ),
      child: Text(
        message,
        style: TextStyle(color: colors.danger, fontWeight: FontWeight.w700),
      ),
    );
  }
}

String _personLabel(Map<String, dynamic> person) {
  final parts =
      [person['last_name'], person['first_name'], person['middle_name']]
          .where((value) => value != null && '$value'.trim().isNotEmpty)
          .map((value) => '$value');
  final label = parts.join(' ').trim();
  return label.isEmpty ? 'Персона #${person['person_id']}' : label;
}

String? _optional(String value) {
  final text = value.trim();
  return text.isEmpty ? null : text;
}
