---
name: unity-csharp
description: |
  Unity C# コーディングパターン。MonoBehaviour ライフサイクル、ScriptableObject、UniTask/async、Unity 固有のアンチパターンを提供する。.cs 編集時に自動参照。
user-invocable: false
---

# Unity C# Coding Patterns

.cs ファイル編集時に自動参照されるコーディングガイド。unity-cli 不要。

## 1. MonoBehaviour Lifecycle

### 実行順序

```
[Awake] → [OnEnable] → [Start]
                ↓
        ── Game Loop ──
       |                |
  [FixedUpdate]    [Update]
       |                |
       |          [LateUpdate]
        ── ── ── ──
                ↓
[OnDisable] → [OnDestroy]
```

- `Awake`: 自分自身の初期化。他オブジェクトへの参照取得
- `OnEnable`: イベント購読の登録
- `Start`: 他オブジェクトの `Awake` 完了後に呼ばれる。相互依存の初期化に使う
- `OnDisable`: イベント購読の解除
- `OnDestroy`: リソース解放

### よくある間違い

```csharp
// NG: Awake で他コンポーネントの初期化結果に依存
// GameManager.Instance は別オブジェクトの Awake で初期化されるため null になりうる
void Awake() { _config = GameManager.Instance.Config; }

// OK: Start で取得（全 Awake 完了後に呼ばれる）
void Start() { _config = GameManager.Instance.Config; }
```

```csharp
// NG: OnDestroy で解除 → 無効化時にリークする
void OnEnable()   { EventBus.OnDamage += HandleDamage; }
void OnDestroy()  { EventBus.OnDamage -= HandleDamage; }

// OK: OnEnable/OnDisable で対にする
void OnEnable()   { EventBus.OnDamage += HandleDamage; }
void OnDisable()  { EventBus.OnDamage -= HandleDamage; }
```

### Script Execution Order

`Awake`/`OnEnable` の順序を制御する必要がある場合:

- Project Settings > Script Execution Order で設定
- または `[DefaultExecutionOrder(-100)]` 属性を使う

```csharp
[DefaultExecutionOrder(-100)]
public class GameManager : MonoBehaviour { }
```

## 2. ScriptableObject Patterns

### 設定データ

ランタイムで変更しない設定値を ScriptableObject に格納する。

```csharp
[CreateAssetMenu(fileName = "EnemyConfig", menuName = "Config/Enemy")]
public class EnemyConfig : ScriptableObject
{
    [field: SerializeField] public float MoveSpeed { get; private set; } = 5f;
    [field: SerializeField] public int MaxHp { get; private set; } = 100;
    [field: SerializeField] public AnimationCurve DamageCurve { get; private set; }
}
```

`field: SerializeField` により Inspector 表示可能かつ外部から変更不可にする。

### イベントチャンネル

ScriptableObject をイベントのハブとして使うパターン。MonoBehaviour 間の直接参照を排除する。

```csharp
[CreateAssetMenu(menuName = "Events/Void Event")]
public class VoidEventChannel : ScriptableObject
{
    readonly List<Action> _listeners = new();

    public void Register(Action listener) => _listeners.Add(listener);
    public void Unregister(Action listener) => _listeners.Remove(listener);

    public void Raise()
    {
        // 逆順で呼び出し: 途中で Unregister されても安全
        for (var i = _listeners.Count - 1; i >= 0; i--)
            _listeners[i]?.Invoke();
    }
}
```

```csharp
// 使う側
[SerializeField] VoidEventChannel _onPlayerDeath;

void OnEnable()  { _onPlayerDeath.Register(HandlePlayerDeath); }
void OnDisable() { _onPlayerDeath.Unregister(HandlePlayerDeath); }
```

### Runtime Data Container

シーンをまたぐデータ共有に使う。DontDestroyOnLoad のシングルトンを避けられる。

```csharp
[CreateAssetMenu(menuName = "Runtime/Player State")]
public class PlayerState : ScriptableObject
{
    public int CurrentHp;
    public Vector3 LastCheckpoint;

    public void Reset()
    {
        CurrentHp = 100;
        LastCheckpoint = Vector3.zero;
    }

    // Play Mode 終了時にリセットするためのフック
    void OnEnable() => Reset();
}
```

注意: `OnEnable` は Editor でアセット読み込み時にも呼ばれる。Play Mode 限定の初期化が必要なら `[RuntimeInitializeOnLoadMethod]` を使う。

## 3. UniTask / async Patterns

### Coroutine からの移行

```csharp
// Coroutine (旧)
IEnumerator FadeOut(CanvasGroup group)
{
    while (group.alpha > 0)
    {
        group.alpha -= Time.deltaTime;
        yield return null;
    }
}

// UniTask (新)
async UniTask FadeOutAsync(CanvasGroup group, CancellationToken ct)
{
    while (group.alpha > 0)
    {
        group.alpha -= Time.deltaTime;
        await UniTask.Yield(ct);
    }
}
```

### CancellationToken の扱い

GameObject の破棄時にキャンセルする:

```csharp
public class Enemy : MonoBehaviour
{
    async UniTaskVoid Start()
    {
        var ct = this.GetCancellationTokenOnDestroy();
        await PatrolAsync(ct);
    }

    async UniTask PatrolAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            await MoveToNextPoint(ct);
            await UniTask.Delay(TimeSpan.FromSeconds(1), cancellationToken: ct);
        }
    }
}
```

OperationCanceledException は握りつぶさず、適切に処理する:

```csharp
try
{
    await LongRunningTask(ct);
}
catch (OperationCanceledException)
{
    // キャンセル時のクリーンアップ
    Debug.Log("Task cancelled");
}
```

### UniTask.WhenAll / WhenAny

```csharp
// 並列実行
var (enemyData, mapData) = await UniTask.WhenAll(
    LoadEnemyDataAsync(ct),
    LoadMapDataAsync(ct)
);

// どちらか一方が完了したら
var idx = await UniTask.WhenAny(
    WaitForPlayerInput(ct),
    TimeoutAsync(10f, ct)
);
```

### UniTaskVoid の使いどころ

戻り値を監視しない fire-and-forget には `UniTaskVoid` を使う。Start や イベントハンドラで使用する。

```csharp
// Start は UniTaskVoid を返せる
async UniTaskVoid Start()
{
    await InitializeAsync(this.GetCancellationTokenOnDestroy());
}
```

`UniTaskVoid` は await できない。例外はログに出るが呼び出し元に伝播しない点に注意。

## 4. Serialization

### SerializeField vs public

```csharp
// NG: public フィールドは外部からの変更を許してしまう
public float speed = 5f;

// OK: SerializeField で Inspector 公開 + 外部非公開
[SerializeField] float _speed = 5f;
```

### SerializeReference

interface やポリモーフィックなフィールドをシリアライズする:

```csharp
public interface IDamageModifier
{
    float Apply(float baseDamage);
}

[Serializable]
public class CriticalModifier : IDamageModifier
{
    [SerializeField] float _multiplier = 2f;
    public float Apply(float baseDamage) => baseDamage * _multiplier;
}

public class Weapon : MonoBehaviour
{
    [SerializeReference] List<IDamageModifier> _modifiers = new();
}
```

`SerializeReference` は Unity 2019.3+。Inspector でのタイプ選択には PropertyDrawer かサードパーティ (Odin 等) が必要。

### JSON シリアライズ

`JsonUtility` は MonoBehaviour / ScriptableObject を直接扱えるが制約が多い:

- Dictionary 非対応
- ポリモーフィズム非対応
- null フィールドが空オブジェクトになる

複雑な構造には `Newtonsoft.Json` (com.unity.nuget.newtonsoft-json) を使う。

## 5. Unity Anti-Patterns

### Update 内のアロケーション

```csharp
// NG: 毎フレーム GC Alloc
void Update()
{
    var hits = Physics.RaycastAll(transform.position, transform.forward);
    var enemies = FindObjectsOfType<Enemy>();
    var msg = $"HP: {_hp}";
}

// OK: 事前確保 + NonAlloc
readonly RaycastHit[] _hitBuffer = new RaycastHit[32];
readonly Collider[] _overlapBuffer = new Collider[32];

void Update()
{
    int count = Physics.RaycastNonAlloc(
        transform.position, transform.forward, _hitBuffer);

    // StringBuilder で文字列結合
    _sb.Clear();
    _sb.Append("HP: ");
    _sb.Append(_hp);
}
```

### string 比較

```csharp
// NG: tag は内部で文字列アロケーション
if (other.tag == "Player") { }

// OK: CompareTag は GC 不要
if (other.CompareTag("Player")) { }
```

### Find 系メソッドの多用

```csharp
// NG: 毎フレーム検索
void Update()
{
    var player = GameObject.Find("Player");
    var rb = GetComponent<Rigidbody>();
}

// OK: キャッシュする
Rigidbody _rb;
Transform _player;

void Awake()
{
    _rb = GetComponent<Rigidbody>();
    _player = GameObject.Find("Player").transform;
}
```

### Camera.main

```csharp
// NG: Camera.main は毎回 FindWithTag を呼ぶ (2020.2 未満)
void Update()
{
    var cam = Camera.main;
}

// OK: キャッシュ (Unity 2020.2+ ではキャッシュ済みだが明示する方が安全)
Camera _mainCam;
void Awake() { _mainCam = Camera.main; }
```

### LINQ in Hot Path

```csharp
// NG: LINQ はアロケーションを伴う
void Update()
{
    var alive = _enemies.Where(e => e.IsAlive).ToList();
    var nearest = _enemies.OrderBy(e => e.Distance).First();
}

// OK: for ループで処理
void Update()
{
    _aliveBuffer.Clear();
    for (var i = 0; i < _enemies.Count; i++)
    {
        if (_enemies[i].IsAlive)
            _aliveBuffer.Add(_enemies[i]);
    }
}
```

### Instantiate / Destroy の頻発

弾丸やエフェクトなど頻繁に生成・破棄するオブジェクトにはオブジェクトプールを使う:

```csharp
// UnityEngine.Pool (Unity 2021.1+)
ObjectPool<Bullet> _pool;

void Awake()
{
    _pool = new ObjectPool<Bullet>(
        createFunc: () => Instantiate(_prefab),
        actionOnGet: b => b.gameObject.SetActive(true),
        actionOnRelease: b => b.gameObject.SetActive(false),
        actionOnDestroy: b => Destroy(b.gameObject),
        maxSize: 100
    );
}

Bullet Get() => _pool.Get();
void Return(Bullet b) => _pool.Release(b);
```

## 6. Editor Scripting Patterns

### CustomEditor

Inspector をカスタマイズする:

```csharp
#if UNITY_EDITOR
[CustomEditor(typeof(EnemySpawner))]
public class EnemySpawnerEditor : Editor
{
    public override void OnInspectorGUI()
    {
        DrawDefaultInspector();

        var spawner = (EnemySpawner)target;
        if (GUILayout.Button("Spawn Test Enemy"))
        {
            spawner.SpawnEnemy();
        }
    }
}
#endif
```

Editor スクリプトは `#if UNITY_EDITOR` で囲むか、`Editor/` フォルダに配置する。Assembly Definition を使う場合は Editor 専用 asmdef を作る。

### PropertyDrawer

特定の型やアトリビュートに対する描画をカスタマイズする:

```csharp
// Attribute 定義
public class ReadOnlyAttribute : PropertyAttribute { }

// Drawer (Editor フォルダに配置)
#if UNITY_EDITOR
[CustomPropertyDrawer(typeof(ReadOnlyAttribute))]
public class ReadOnlyDrawer : PropertyDrawer
{
    public override void OnGUI(Rect position, SerializedProperty property,
        GUIContent label)
    {
        GUI.enabled = false;
        EditorGUI.PropertyField(position, property, label);
        GUI.enabled = true;
    }
}
#endif
```

### EditorWindow

ツール用のウィンドウを作成する:

```csharp
#if UNITY_EDITOR
public class LevelToolWindow : EditorWindow
{
    [MenuItem("Tools/Level Tool")]
    static void Open() => GetWindow<LevelToolWindow>("Level Tool");

    string _searchQuery;

    void OnGUI()
    {
        _searchQuery = EditorGUILayout.TextField("Search", _searchQuery);

        if (GUILayout.Button("Find Objects"))
        {
            var results = FindObjectsByType<Transform>(
                FindObjectsSortMode.None);
            // ...
        }
    }
}
#endif
```

### SerializedProperty の操作

`Undo` 対応と multi-object editing のため、直接フィールドを触らず `SerializedProperty` を使う:

```csharp
public override void OnInspectorGUI()
{
    serializedObject.Update();

    var speedProp = serializedObject.FindProperty("_speed");
    EditorGUILayout.PropertyField(speedProp);

    serializedObject.ApplyModifiedProperties();
}
```
