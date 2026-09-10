# Silksong Godhome

> ### 🛑 Development has stopped
>
> This went a long way - further, as far as we can tell, than any previous attempt to
> port Godhome into Silksong - and then stopped. Godhome's rooms rebuild with their
> architecture, lighting, doors, benches, statues and Pantheon doors; the Pantheons
> start; the bosses appear in their own arenas with Hollow Knight's own FSMs running
> their own state graphs; the music plays. What never came together is a boss *fight*
> you can finish. See [Where it got to](#where-it-got-to) for an honest account, and
> [Why there is still hope](#why-there-is-still-hope) for what a future attempt should
> know - because nothing here turned out to be impossible, which is the point.
>
> Not maintained. Issues and PRs will not be answered. Fork it freely.
>
> **It ships no Hollow Knight assets.** `SilksongGodhome/Baked/` is gitignored on
> purpose - you regenerate it from your own copy of Hollow Knight with
> `tools/extract_godhome.py`. You need to own both games.

Ports Hollow Knight's **Godhome** into Silksong as a Godseeker game mode: pick it from
the play-mode menu and you wake up in the Atrium as Hornet, with the Pantheons ahead of
you.

## Why this is tractable

Silksong is built on Hollow Knight's codebase, and Team Cherry never stripped the
Godmaster systems out of it. Still live in Silksong's `Assembly-CSharp.dll`:

| Class | Lines | What it does |
| --- | --- | --- |
| `BossSequenceController` | 471 | runs a Pantheon |
| `BossSequenceDoor` | 410 | the Pantheon doors and their completion state |
| `BossStatue` | 508 | statues, dream variants, unlock indicators |
| `BossSceneController` | 330 | per-arena boss lifecycle |
| `BossScene`, `BossSequence`, `BossDoorChallengeUI` | ~530 | bindings, challenge UI |

...plus the whole `GG*` PlayMaker action set (`GGCheckBossSceneUnlocked`, `GGReturn`,
`GGUnlock`, `GGCheckIsBossRushMode`, ...) and the scene constants:

```csharp
public const string BOSSRUSH_END_SCENE    = "GG_End_Sequence";
public const string GG_ENTRANCE_SCENE     = "GG_Entrance_Cutscene";
public const string GG_DOOR_ENTRANCE_SCENE= "GG_Boss_Door_Entrance";
public const string GG_RETURN_SCENE       = "GG_Waterways";
public const string RECORD_BOSSRUSH_MODE  = "RecBossRushMode";
```

Even the menu entry is already built. `Menu_Title` ships **three**
`StartGameEventTrigger` components - `(permaDeath 0, bossRush 0)`,
`(permaDeath 1, bossRush 0)` and `(permaDeath 0, bossRush 1)`. That third one is a fully
authored menu button; it's just gated off:

```csharp
if (bossRush && GameManager.instance.GetStatusRecordInt("RecBossRushMode") == 0)
    result = false;   // StartGameEventTrigger.IsFulfilled()
```

So the mod doesn't invent a game mode. It finishes one.

## What was actually missing

1. **The menu gate.** Nothing in the shipped game ever sets `RecBossRushMode`.
   `ModeUnlock` sets it from a postfix on `GameManager.SetupStatusModifiers` - the same
   place the game would, if `gameConfig.unlockBossRushMode` were true.

2. **The save state.** `PlayerData.AddGGPlayerDataOverrides()` has an **empty body**.
   It's called from the boss-rush branch of `GameManager.StartNewGame`, which then runs
   `RunContinueGame()` rather than `RunStartNewGame()` - it deliberately skips the
   opening and loads from the save's respawn point. With an empty override you'd be
   dumped at the normal start of the game with nothing. `GodhomeLoadout` fills it in:
   Hornet's full kit, `bossRushMode = true`, and a respawn point inside Godhome.

3. **The scenes.** Silksong ships **zero** `GG_*` scenes. All 78 of them
   (`GG_Atrium`, `GG_Workshop`, 52 boss arenas...) exist only in Hollow Knight.

## The engine gap, and how scenes get across

Hollow Knight is Unity **2020.2.2f1**; Silksong is Unity **6000.0.50f1**. AssetBundles
are version-locked, so HK's compiled scenes can't be loaded by Silksong at any price.

What *is* portable is the *description* of a scene. `tools/extract_godhome.py` reads
HK's `levelN` files with UnityPy and bakes out a transform hierarchy, sprite table,
collider set and atlas pages. The csproj embeds that into the DLL, and
`Rebuild/SceneRebuilder.cs` reconstructs it as live GameObjects at runtime.

Because the GG scene names are still hard-coded all over the game,
`Rebuild/SceneRedirect.cs` intercepts `GameManager.BeginSceneTransition`, swaps a
`GG_*` request for a small real room (the *donor*), and lets the rebuilder empty that
room and construct Godhome inside it. The engine's transition, camera, hero-spawn and
`SetupSceneRefs` machinery all behave normally, because from its point of view an
ordinary scene loaded.

## Build

```
dotnet build -c Release
```

Copies `SilksongGodhome.dll` into `BepInEx/plugins/SilksongGodhome/`. Requires BepInEx 5.

The game path lives in `Directory.Build.props`. Rather than edit that tracked file, drop
a gitignored `LocalPaths.props` beside it:

```xml
<Project>
  <PropertyGroup>
    <GamePath>C:\Program Files (x86)\Steam\steamapps\common\Hollow Knight Silksong</GamePath>
  </PropertyGroup>
</Project>
```

### Baking the scenes

`SilksongGodhome/Baked/` is **gitignored** - it holds Hollow Knight's art, which
shouldn't be committed. Regenerate it from your own HK install:

```
cd tools
python3 extract_godhome.py                    # GG_Atrium
python3 extract_godhome.py --list             # every Godhome scene in the build
python3 extract_godhome.py --all              # all 78
python3 extract_godhome.py --scenes GG_Workshop GG_Atrium
```

Needs `UnityPy` and `Pillow`. Then rebuild the DLL so the new data is embedded.

Default bake is 17 scenes: the five hub rooms - `GG_Atrium`, `GG_Workshop` (the Hall of
Gods), `GG_Atrium_Roof`, `GG_Blue_Room`, `GG_Land_of_Storms` - plus the twelve Pantheon
of the Master arenas. That comes to roughly 195 MB of baked data and a ~177 MB DLL:
mostly Hollow Knight's tk2d atlases, which are genuinely used art. Rooms themselves are
deflated (about 15% of their raw size) and music is IMA ADPCM.

Bake for `GG_Atrium`: 1,782 objects, 1,277 sprite renderers, 106 unique sprites,
134 colliders, 17 camera lock areas, 2 respawn + 9 hazard markers, 6 shaders, and the
scene's real 190x90 bounds - **4.07 MB** (the raw HK atlas pages would be 16.4 MB;
`repack.py` crops to only the rects the scene uses).

Hollow Knight ships no type trees for MonoBehaviours, so 361 of GG_Atrium's 385
components can't be deserialised by UnityPy at all. `monoread.py` parses them from raw
bytes against field layouts taken from decompiling HK's own `Assembly-CSharp` - which is
how `CameraLockArea`, the respawn markers and the tilemap's dimensions get across.

### The Pantheon challenge screen

`tools/bake_ui.py` lifts Hollow Knight's four binding icons (nail, shell, charm, soul -
lit and unlit) out of GG_Atrium's asset closure, so the challenge screen shows the real
icons rather than text. Run it once alongside `extract_godhome.py`:

```
python3 bake_ui.py
```

The screen's layout is ours - the real `BossDoorChallengeUI` is a Canvas prefab (Animator
with Open/Close clips, four wired `BossDoorChallengeUIBindingButton`s) that can't be
reconstructed - but the icons, the font (`TrajanPro-Bold`, borrowed off a live UGUI Text)
and the four-binding shape come from the game.

### Checking a bake without launching the game

```
python3 verify_baked.py    # reads it back exactly as GodhomeData.cs does
python3 preview_scene.py   # renders it to /tmp/GG_Atrium_preview.png
```

`verify_baked.py` confirms writer and reader agree field-for-field (it fails on any
trailing or short read). `preview_scene.py` applies the same world transforms and
rect/pivot maths as `SceneRebuilder`, so if it looks like Godhome, the extraction is
right.

## Layout

```
Directory.Build.props          game path
SilksongGodhome/               the plugin
  Plugin.cs                    BepInEx entry point
  GodhomeConfig.cs             config bindings
  GodhomePatches.cs            every Harmony hook, in one place
  ModeUnlock.cs                reveals + relabels Silksong's own boss-rush button
  GodhomeLoadout.cs            fills in the empty AddGGPlayerDataOverrides
  GodhomeManager.cs            per-frame + scene-change driver
  Rebuild/
    SceneRedirect.cs           GG_* -> donor room, remembering what was asked for
    GodhomeData.cs             reads the embedded baked format
    SceneRebuilder.cs          baked data -> live GameObjects
  Baked/                       generated, gitignored
tools/
  extract_godhome.py           the baker
  hkassets.py                  HK loading + per-file PPtr resolution
  spritebake.py                sprite -> atlas page + rect + corrected pivot
  repack.py                    crops HK's shared atlases down to what's used
  ggformat.py                  the format, shared by writer and reader
  verify_baked.py              format round-trip check
  preview_scene.py             renders a bake to PNG
```

## Controls

All configurable in `BepInEx/config/com.faaris.silksonggodhome.cfg`.

| key | |
| --- | --- |
| `F10` | rebuild and warp straight to `GG_Atrium` (skips the menu; for iterating) |
| `F8` | during a Pantheon run, skip to the next arena |
| `F6` | spawn the boss named in `SpawnBossName` where you stand |

Boss FSM state changes are logged by default (`TraceBossStates`); that log is the most
useful thing in the project for working out why a fight is not progressing.

## Where it got to

Final state, honestly.

**Works, and was seen working in game:**

* The Godseeker entry on the play-mode menu, revealed and relabelled, running through
  Silksong's own `BossSequenceController`.
* A Godhome save slot with its own area art and name; save-and-quit returns you to it.
* 17 rooms bake and verify byte-exact - the five hub rooms plus all twelve Pantheon of
  the Master arenas - with architecture, terrain meshes, colliders, camera lock areas,
  respawn markers, transitions, scene bounds and Hollow Knight's own colour grading.
* Walking between rooms, the bench, the Hall of Gods statues, the Pantheon doors and
  their challenge UI.
* Bosses appear in their own arenas and run Hollow Knight's own FSM graphs. The last
  log before development stopped has Gruz Mother going
  `Big Fly Control (start) -> Wake -> GG Extra Pause -> Buzz`, with `bouncer_control`
  and her collision FSM alongside, and `BossSceneController from the room is set up`.
* Godhome's music, all eighteen tracks, played by the arena's own `ApplyMusicCue`
  actions at the moments Hollow Knight asks for them.

**Never came together:** a boss fight you can play to the end. Individually: False
Knight's head mechanic, Mega Moss Charger's burrow, Hornet's needle throw, Gorb's
needles, Brooding Mawlek staying visible, Oro's jump. Death animations and hit knockback
were wired but never confirmed in play.

**Never started:** the other 40 arenas, the four higher Pantheons, the Hall of Gods
statue challenges, bindings.

## Why there is still hope

Nothing found here was impossible. That is worth saying plainly, because it is the
opposite of how a stalled port usually ends.

Three measurements, all reproducible from this repo:

| | | how to check |
| --- | --- | --- |
| Godhome components Silksong still defines | **1863 of 1892** instances, only 4 distinct types absent | `tools/compaudit.py` |
| PlayMaker actions the bosses use that Silksong still has | **93 of 93** | `tools/actionaudit.py` |
| Component layouts derived automatically and read byte-exactly | **1289**, with **0** wrong | `tools/layoutaudit.py` |

Hollow Knight's FSMs parse byte-exactly and load into Silksong's own PlayMaker as real
actions - they are never interpreted or approximated. Its components are Silksong's
components, by name, running the game's own code. Its sprite collections and animation
libraries are byte-identical between the two copies of tk2d. There is no wall here.

**What actually stopped it was the iteration loop.** A boss fight is an integration of
several hundred small things - one FSM variable, one object reference, one collider
layer - and each can fail silently and only in play. Every diagnosis cost a round trip
through a human launching the game and describing what they saw. That is the bottleneck
a next attempt should attack first, before any more content:

1. **A way to test a fight without a person watching it.** Drive the game to an arena,
   run the fight, and diff the FSM state trace against Hollow Knight's. `BossTrace`
   already logs every state change; what is missing is the harness and a recorded
   reference trace to compare against.
2. **`FunctionCall` parameters.** `SendMessage` actions fail to load because these are
   baked as null placeholders (`FsmBuilder.PopulateActionData`). Small, and it silently
   breaks whichever states use them.
3. **The FSM object references that still resolve to nothing.** Baked references cover
   in-scene objects, prefabs, sounds and ScriptableObjects. Whatever is left is where
   the remaining fights break.
4. **Only then, more arenas.** The pipeline handles them already; it is the fights that
   need the work.

If you pick this up: read the commit messages. Every non-obvious thing this project
learned is written down in one, at the point it was learned, with the evidence that
settled it.

### The donor scene must be a standalone room### The donor scene must be a standalone room

Silksong composes rooms from a main scene plus additive sub-scenes, and the names look
alike. `Bone_05_bellway` is **not** a room - it's an additive chunk holding only the Bone
Beast NPC, with no `_SceneManager`, no `TileMap` and no terrain. Building Godhome inside
it left `GameManager.sm` null, and `OnNextLevelReady` does:

```csharp
if (!IsMemoryScene(sm.mapZone))   // no null check
```

which throws before `FadeSceneIn()` is ever reached - so the fade never lifts and the
screen stays black with nothing in the log.

The donor is now `Bone_05`, a real room (`_SceneManager`, `_Managers`, `TileMap`,
`TileMap Render Data`). Three guards came out of this:

* the strip keeps roots by **component and known name**, not name prefixes alone, so it
  can't silently keep nothing again;
* `EnsureSceneManager()` builds a `CustomSceneManager` if the scene somehow lacks one
  (inactive first - its `Awake` iterates `scenePools`, which is null on a fresh
  `AddComponent`) and repoints `GameManager.sm`;
* the kept TileMap roots get their renderers and colliders disabled, so the donor's
  terrain isn't left visible and solid underneath Godhome.

`CrashWatch` now mirrors Unity's own exceptions into the BepInEx log during a Godhome
load, and a watchdog forces the fade if the scene hasn't finished entering after 4s - so
a black screen reports its cause instead of just being black.

**Note:** changing the donor default in code does not rewrite an existing
`BepInEx/config/com.faaris.silksonggodhome.cfg`. Edit `DonorScene` there, or delete the
file to regenerate it.

### Never build a scene manager when the room has one

The second live test still black-screened, with three exceptions that turned out to be
one cause. `EnsureSceneManager` only reused the donor's `_SceneManager` when
`GameManager.sm` was already set - and it isn't set that early - so it built a synthetic
`CustomSceneManager` alongside the perfectly good one it had just kept. A bare
`CustomSceneManager` has an unconfigured `SceneColorManager`, and `Start()` walks its
colour curves:

```
SceneColorManager.PairKeyframes -> PairCurvesKeyframes -> UpdateScript
  -> CustomSceneManager.UpdateScene -> CustomSceneManager.Start     (NRE)
```

That cascades: `GameCameras.StartScene()` dies the same way, which leaves
`screenFader_fsm` null, so `GameManager.EnterHero()` throws on it too. The fix is to
always prefer the donor's own scene manager and only synthesise one as a genuine last
resort.

### Bake every collider, not one per object

Godhome's floor is `EdgeCollider2D`s on the tilemap chunks - and a chunk carries several
on one GameObject (`Chunk 1 4` has four). The extractor keyed components by type name in
a dict, so it kept one per object and silently dropped 13 of GG_Atrium's 28 edge
colliders, most of the floor with them. Format v3 stores a count per collider type.

`tools/groundcheck.py` exists to catch exactly this: it finds the highest baked edge
beneath the respawn marker and reports the drop. For GG_Atrium the spawn is at
(14.69, 35.11) with ground at y=34.00 - a 1.11 unit drop, which is right.

### Godhome's interactables, and what Silksong has for each

Every Godhome interaction was checked against Silksong's own implementation rather than
reinvented. Three outcomes: the class survives and is re-attached with baked field data;
the class survives but needs prefab wiring we can't reconstruct, so the *presentation* is
ours and the *logic* is still Silksong's; or it's pure FSM and not ported yet.

| Godhome thing | Hollow Knight | Silksong | What the mod does |
| --- | --- | --- | --- |
| Room doors | `TransitionPoint` | `TransitionPoint`, same fields | Re-attached from baked data; `SceneRedirect` catches the target |
| Camera bounds | `CameraLockArea` | `CameraLockArea`, same 4 floats + flags | Re-attached |
| Spawn point | `RespawnMarker` | `RespawnMarker`; `HeroController.LocateSpawnPoint` matches on GameObject name | Re-attached; HK's own "Death Respawn Marker" is the Godseeker spawn |
| Hazard respawn | `HazardRespawnMarker` | Same, but facing became a private enum | Re-attached; facing set by reflection when present |
| Scene colour/lighting | `SceneManager` fields | `CustomSceneManager`, identical field names | Values copied over, `overrideColorSettings` forced |
| Scene bounds | `tk2dTileMap.width/height` | `CameraController` reads the same | Donor tilemap resized to Godhome's |
| Terrain | tk2d chunk meshes | plain `MeshFilter`/`MeshRenderer` | Meshes decoded and rebuilt |
| Bench | "Bench Control" FSM | **Still looks up an FSM by that exact name**; `PlayerData.atBench`, `RestBenchHelper` are public C# | `GodhomeBench` heals and saves. It deliberately does *not* set a respawn point - Godhome's bench is for healing and swapping tools between attempts, and dying in a Pantheon returns you to the Atrium |
| Pantheon entrance | `BossSequenceDoor` + challenge FSM | `BossSequenceDoor` exists; `BossSequenceController.SetupNewSequence` is **public static** | `PantheonDoor` draws the prompt, then calls `SetupNewSequence` - the same call HK's FSM makes |
| Pantheon run | `BossSequence` assets in `Resources/GG` | `BossSequence`/`BossScene` classes intact, assets absent | Rebuilt as live ScriptableObjects from `sequences.bin` |
| Statue: strike | `BossStatueLever` (nail) | **`BossStatueLever` is fully implemented** and checks `collision.tag == "Nail Attack"` | `GodhomeStatue` uses the same tag, so Hornet's needle swaps the statue |
| Statue: dream tier | `BossStatueDreamToggle` (dream nail) | class exists; Silksong has no dream nail | Folded into the needle strike - one swap between base and dream fight |
| Statue: fight | `bossUIControlFSM` | FSM absent | Press Up; loads that statue's arena |
| Glows / hazes | `UI/BlendModes/Screen` | **no such shader**; `Sprites/Default` hard-codes its blend state | Premultiplied at bake time, drawn with `Legacy Shaders/Particles/Alpha Blended Premultiply` |
| Pantheon binding screen | `BossDoorChallengeUI` prefab | class exists, prefab doesn't | Screen drawn by `PantheonChallengeUI`; the four flags go to Silksong's own `ChallengeBindings` and `ApplyBindings` |
| Bench: sitting | "Bench Control" FSM sends `BENCHREST` | hero prefab still has `BENCHREST` / `BENCHREST END` states and `Hornet_sit####` frames | `GodhomeBench` fires those events at the hero |
| Water / hazards | FSM | FSM | Not ported |

The pattern worth noting: **Silksong's Godhome C# is not just present, it's reachable.**
`SetupNewSequence` being public static is what lets a Pantheon start without a single FSM.

### Sprites were mirrored and upside down

Roughly one Godhome sprite in eight came out mirrored or inverted - most visibly the gods
in the Hall of Gods, which were upside down.

Unity stores atlas-packed sprites *with* a packing transform already applied and reverses
it through the sprite's UVs. `settingsRaw` bits 2-4 hold that transform, and the extractor
was ignoring them while cropping straight out of the page. For GG_Workshop's closure:

| packing rotation | entries |
| --- | --- |
| none | 5985 |
| flipV | 301 |
| flipH | 298 |
| rot180 | 243 |

`repack.unpack_rotation` now undoes it at bake time, so nothing is needed at runtime.

### Godhome's audio

`audiobake.py` decodes each AudioSource's clip out of Hollow Knight's streamed `.resource`
files, downmixes to mono, resamples to 22050 Hz and stores 16-bit PCM - which is exactly
what `AudioClip.SetData` wants, so there's no decoder at runtime. Raw stereo PCM would be
about eight times larger (one 16-second clip is 2.8 MB on its own).

Clip files are named after the clip, so sounds shared between rooms are stored once.
GG_Atrium alone has 52 sources on 20 clips - the waterfalls, the golden hum,
`gg_door_lock_break`, the boss-rush door.

### Bosses: the FSM parser

The blocker for porting a boss was never the art or the components - it was PlayMaker.
A boss's behaviour lives entirely in FSM graphs, and Hollow Knight ships no type trees
for MonoBehaviours, so the graphs are opaque bytes.

They are no longer opaque. `tools/fsmparse.py` parses a `PlayMakerFSM` component straight
out of Hollow Knight's serialised bytes - the whole graph: states, transitions, events,
variables, and each state's `ActionData`.

**Validation.** The correctness claim is falsifiable: parse a component and the cursor
must land exactly on the end of its buffer. `tools/fsmvalidate.py` runs that over every
baked arena:

```
TOTAL: 679 FSMs byte-exact, 0 failed, 7104 states, 22843 actions
```

Gruz Mother's own `Big Fly Control` is 30 states and 189 actions, and parses exactly.

Getting there needed five corrections that only byte-exactness would have caught:

* `ActionData.byteDataAsArray` is `[NonSerialized]`, and `nextParamIndex` is private with
  no `[SerializeField]` - neither is in the stream.
* `FsmVariables` has a `variableCategoryIDs` array after `categories`.
* `Fsm` has 19 more fields after `handleCollisionExit2D`.
* `FsmVarOverride.variable` is declared as the base `NamedVariable`, and Unity serialises
  a non-`[SerializeReference]` polymorphic field as its declared type only.
* **`FsmMaterial` and `FsmTexture` derive from `FsmObject`, not `NamedVariable`** - so they
  carry its `typeName` string too, 36 bytes rather than 32. This one showed up as a stray
  `1.0f` where a string length belonged.

**Why this makes porting viable.** Every `[SerializeField]` in `ActionData` is identical
between Hollow Knight's PlayMaker 1.9.0 and Silksong's 1.9.9. So the parsed arrays can be
handed back to Silksong's own `ActionData`, and `ActionData.LoadActions` builds the live
action instances - we never have to understand what any individual action does.

### Making a boss fight

Art and FSMs aren't enough - a boss also needs the parts that make it an enemy, and those
are baked from Hollow Knight's own values rather than guessed. Gruz Mother:

| | |
| --- | --- |
| Rigidbody2D | dynamic, gravityScale 0, FreezeRotation - her FSM drives movement entirely through SetVelocity2d |
| Body hitbox | BoxCollider2D 3.52 x 1.52, offset (0.148, -0.805), layer 11 (Enemies) |
| Contact damage | a child `Hero Damager`, trigger collider 2.03 x 1.5, `DamageHero(1, hazardType 1)` - and **inactive by default**, because her FSM switches it on mid-attack |
| Health | `HealthManager.hp = 650` (Godhome tier) |

The physics layers line up between the games (8 Terrain, 9 Player, 11 Enemies, 17 Attack,
20 Hero Box), so layer numbers transfer directly.

**Waking her up.** `Big Fly Control` starts in Init, which runs `GGCheckIfBossScene`:

```
GG BOSS  -> GG Boss Wake -> Wake -> Fly     (in a Godhome arena)
FINISHED -> Invincible                      (everywhere else)
```

and from Invincible the normal-game route is
`HERO ENTER -> Sleep -> TAKE DAMAGE -> Wake Sound -> Wake -> Fly`, where HERO ENTER comes
from the arena's Battle Range trigger. A boss dropped in by the debug key has no arena, so
`BossWaker` sends those same events in the same order and stops as soon as the FSM leaves
its idle states. It supplies the inputs the scene normally would; it doesn't override the
boss's logic.

Faking a `BossSceneController` would have been the other route, but its `Awake` pulls on
sequence loading, which is a lot of machinery to satisfy for one boolean.

### Godhome saves look like Godhome

A Godseeker save now shows Godhome's own art and the name "Godhome" on the save-select
screen, and loading it puts you back at your Godhome respawn point.

Silksong already distinguishes these saves - `SaveStats.BossRushMode` is read straight
out of the save file (`playerData.bossRushMode`, which the Godseeker loadout sets), so
nothing has to be inferred. The slot's art and label are chosen in
`SaveSlotButton.PresentSaveSlot`, so a postfix there overrides just those two pieces.
The `AreaBackground.NameOverride` route was the obvious one but its `LocalisedString`
resolves through a localisation sheet the mod doesn't ship, so it would have rendered as
a missing-key placeholder.

**Loading back in** needed one more fix. `GameManager.GetRespawnInfo` validates the saved
scene and marker against `SceneTeleportMap` and, on a miss, silently rewrites them to
`Tut_01`. The hub is registered at boot, but a save made at Godhome's bench points at that
bench's marker, which only exists once the scene has been rebuilt - so a cold launch would
drop you in the tutorial. A postfix restores the saved values whenever they name a Godhome
scene we have baked.

Drop your own art in as `SilksongGodhome/Baked/ui_area_godhome.png`.

### Bosses in their own arenas, with their own sounds

Each baked boss records the Hollow Knight scene it came from, so `BossRegistry` indexes
them by arena (reading only each file's header) and `SceneRebuilder` puts them back where
Hollow Knight had them when that arena is rebuilt. The debug key still works for dropping
one anywhere.

Two things had to be right for a boss to land in the right place:

* **World, not local, position.** A boss's transform is local to whatever it's parented
  under, and in Hollow Knight that's often an offset container - False Knight and Brooding
  Mawlek both sit under a "Battle Scene" object roughly 14 units across and 32 up, so
  spawning at their local position put them well outside the arena. The root is baked in
  world space now; children keep their local transforms.
* **No nested duplicates.** Boss discovery looks for `HealthManager` + `tk2dSpriteAnimator`,
  which also matches False Knight's `Head` - a child of False Knight that's already baked
  as part of him. Candidates that sit inside another candidate are dropped, so he doesn't
  arrive with a second head floating beside him. Mato and Oro are siblings rather than
  nested, so both survive.

**Sound effects transfer.** A boss's FSM references its clips through `fsmObjectParams`
with `typeName = "UnityEngine.AudioClip"` - Gruz Mother has four
(`big_fly_flying`, `big_fly_charge_loop`, `big_fly_wall_hit`, `big_fly_snore_startle`),
Mato and Oro have thirty each. Those are baked like any other audio and re-linked by name
when the FSM is rebuilt, so `AudioPlay` actions find a real clip. Everything else a
Hollow Knight FSM points at - spawned prefabs, mixer snapshots - still can't cross.

### Dying

A boss whose health hit zero just stopped responding. Hollow Knight doesn't handle death
in the boss's FSM - neither of Gruz Mother's even listens for the `"ZERO HP"` event
`HealthManager.Die` sends. Death is `EnemyDeathEffects`, which spawns a separate corpse
prefab and destroys the enemy, and those prefabs are Hollow Knight assets that can't cross
the engine gap.

The animations *can*, though - they're in each boss's own library. So `BossDeath` stops
the FSMs, disables the damager and colliders, plays the boss's real death clip, lets the
body fall, and fades it out.

Clip choice is per-boss because Hollow Knight isn't consistent about it:

| boss | clip |
| --- | --- |
| Gruz Mother, Vengefly King, Moss Charger, Gorb | `Death` |
| Dung Defender | `Death Splat` / `Death Sink` / `Death Fly` |
| False Knight | `Death Fall` -> `Death Land` |
| Hornet, Mage Knight | `Death Air` / `Death Land` |
| Mato, Oro | no death clip at all - the Nailmasters **bow** and then **rest**, which is their defeat in Hollow Knight |
| Brooding Mawlek | nothing usable; fades |

The Nailmasters keep their footing rather than dropping, since bowing is a standing pose.

### What a boss still needs

Gruz Mother, fully scoped:

| Piece | Status |
| --- | --- |
| FSM graphs (2 on the boss) | parser proven |
| Action classes | 56 of 59 present in Silksong; the 3 gaps are numbered duplicates (`FaceObject0` -> `FaceObject`) and can be aliased |
| Components (`HealthManager`, `DamageHero`, `SpriteFlash`, `ExtraDamageable`, `EnemyDeathEffects`) | all present; only `EnemyDreamnailReaction` is missing, and Silksong has no dream nail |
| tk2d animation | 17 clips in a 3 KB library, 19 KB sprite collection - same raw-parse technique, ~4 more type layouts |
| Referenced prefabs | only 4 distinct (`Slam Effect`, `Dust Impact Med`, `Particle Rock Small Transient`, `Audio Player Actor`) plus 10 audio clips |

Remaining work is mechanical rather than unknown: tk2d layouts, recursive prefab
extraction, rebuilding the `Fsm` in C# through reflection, and remapping asset references
onto rebuilt objects.

### Bosses: action-class survey

`tools/boss_survey.py` answers the question that decides whether porting bosses is
possible at all - do Hollow Knight's PlayMaker action classes still exist in Silksong?

For GG_Gruz_Mother: **56 of the boss FSMs' 59 action types are already present**. The
three that aren't (`CheckCollisionSide5`, `FaceObject0`, `SetVelocityAsAngle5`) are Hollow
Knight's numbered duplicates of actions that *do* exist, so they can be aliased.

That makes FSM porting a real prospect rather than a rewrite - both games share PlayMaker
and Team Cherry's custom action set. What it does not make it is small: the remaining work
is parsing PlayMaker's serialised `Fsm` (states, transitions, `ActionData`'s
paramDataType/byteData pairs, variables) and rebuilding it at runtime, plus the boss
GameObject itself - tk2d animator, animation library, HealthManager, colliders.

Until that lands, `PantheonRun` tracks progress and the skip key (default `F8`) advances
through a Pantheon, because nothing else can end an arena.

### Godhome rooms swap in place; they don't load

Entering a Pantheon hung on an infinite loading screen. The first theory - that every
Godhome scene mapped onto the *same* donor, so the game was asked to load the scene it was
already standing in - was wrong: alternating donors (`Bone_05,Bone_03`) made no
difference, it still hung after the redirect with no exception and the game still ticking.

The important realisation is that the transition was never buying anything. Once you are
inside Godhome, *every* room is a rebuild into a donor scene whose contents get thrown
away immediately - so running Unity's full transition pipeline (fetch, activation gates,
`SceneAdditiveLoadConditional.LoadAll`, unload, GC, `BeginScene`) is pure risk for no
gain, and somewhere in there it stalled.

So `SceneRedirect.Intercept` now returns `false` for Godhome-to-Godhome moves, which
cancels `BeginSceneTransition` outright, and `SceneRebuilder.SwapInPlace` tears down
`GodhomeRoot`, builds the next room into the live scene, and places the hero at the named
entry gate (falling back to a respawn marker, then any transition point - the same
fallback order `GameManager.FindEntryPoint` uses). Room changes are now instant.

The first entry into Godhome still uses a real transition, because we have to get into a
gameplay scene at all - and that path was always working.

`LoadWatch` was added while chasing this: it polls `SceneLoad`'s per-phase timings and
reports which phase a load is stuck in, so a hang names itself instead of being guessed at.

### Two fixes worth recording

**Glows, twice.** First they drew as bright rectangles, then they blew the screen out
orange. Both were the same misunderstanding from different ends. The first attempt at screen blend set
`_SrcBlend`/`_DstBlend` on a `Sprites/Default` material - which does nothing, because
Unity's built-in sprite shader hard-codes its blend state and has no such properties. The
symptom was odd: the white hazes washed the screen out, while the caustics (near-black,
96% opaque, invisible under screen blend) became dark occluding squares. Silksong does
ship additive and premultiplied particle shaders. The sprites are premultiplied by their
alpha at bake time - but pairing premultiplied textures with *additive* blending
double-counts them, because additive ignores alpha entirely, so every large haze added
its full value and overlapping glows compounded into a white-out. The correct pairing for
a premultiplied texture is `Legacy Shaders/Particles/Alpha Blended Premultiply`
(`Blend One OneMinusSrcAlpha`): a glow adds its own colour and attenuates the background
by its coverage, keeping screen blend's "never darkens" behaviour while staying bounded.

**The Pantheon doors looked sealed even though they were open.** `BossSequenceDoor.Start()`
normally hides `lockSet` and shows `unlockedSet`; we never attach that component, so the
padlock geometry stayed visible. The extractor now bakes those child object references and
the rebuilder toggles them, which is what an unlocked door does.

Along the way this exposed a latent indexing bug: `bake_scene` skipped objects whose
GameObject failed to resolve, but parent indices were still assigned from the unskipped
hierarchy walk - so a single skip would have silently reparented everything after it.
Parents now resolve through an explicit order-to-object map.

### Where the remaining behaviour lives

*Written partway through, and left as a record of how the approach was arrived at. The
answer it reaches - that the FSMs are the real content - is what the whole-arena bake in
the final commits is built on.*

Silksong has the Godhome *C# classes*. What it doesn't have is Godhome's **PlayMaker FSM
graphs**, and that is where most of the interactivity actually is - benches, doors
opening, statues activating, water, the Pantheon sequences. GG_Atrium alone has 104 FSMs
and GG_Workshop 225. Re-attaching a `RestBench` gets you "near a bench"; the sitting
animation and the save prompt are FSM.

So the split is:

* **Components that exist in both games** - re-attach with baked field data. Done so far:
  `CameraLockArea`, `RespawnMarker`, `HazardRespawnMarker`, `TransitionPoint`, and the
  zero-field ones (`RestBench`, `NonBouncer`, `NonSlider`, `NonThunker`, `Roof`).
  Still to do: `BossStatue` (37 in GG_Workshop), `BossSequenceDoor` (5 in GG_Atrium),
  `BossDoorTargetLock`.
* **FSMs** - the big one, and unavoidable for real Godhome behaviour.

### Postscript

The last thing found, on the last day, is a good example of the kind of problem this
project was made of. Bringing across Hollow Knight's `BlurPlane` components - which the
component audit correctly said Silksong still has - made Godhome's entire background
disappear, because Silksong's camera rig does this every frame:

```csharp
BlurPlane closestBlurPlane = BlurPlane.ClosestBlurPlane;
if (closestBlurPlane != null)
    sceneCamera.farClipPlane = closestBlurPlane.PlaneZ - sceneCamera.z + clipEpsilon;
```

Eleven blur planes rebuilt at Hollow Knight's Z pulled the far clip plane in and clipped
the room out of the scene camera. The boss sat near z=0 and survived; the architecture
did not. The component was real, the port of it was faithful, and it was exactly wrong -
because a depth convention belongs to the host game's camera, not to the content. Every
remaining bug in this project is likely to be that shape.
