# Silksong Pantheons

Hollow Knight's **Godhome** in Silksong — its Atrium, its Hall of Gods, its Pantheon
doors and its challenge screen — but the Pantheons are fought against **Silksong's own
bosses**, in Silksong's own arenas.

> ### 🌱 Early. Nothing is built yet beyond what it inherits.
>
> This is a fresh start on the back of
> [SilksongGodhome](https://github.com/faarisaahmed/SilksongGodhome), which got Godhome
> itself working and then stalled trying to port Hollow Knight's bosses across. That
> code is here and working. What changes is what the Pantheon doors lead to.

---

## Why this is a different problem

The previous attempt died on one thing, and it is worth being precise about what.

Godhome came across fine. The Atrium rebuilds with its real architecture and lighting,
the doors work, the bench works, the Hall of Gods is there, the Pantheon doors open their
challenge screen and start a run through Silksong's own `BossSequenceController`. The
music plays. That is a lot of a boss-rush mode, and it is done.

What could not be finished was **Hollow Knight's bosses**. Not because anything was
impossible — every measurement said the opposite:

| | | |
| --- | --- | --- |
| Godhome components Silksong still defines | 1863 of 1892 instances | only 4 types absent |
| PlayMaker actions the bosses use | 93 of 93 | all present in Silksong |
| Component layouts derived automatically | 1289 read byte-exactly | 0 wrong |

Hollow Knight's FSMs parsed byte-exactly and loaded into Silksong's PlayMaker as real
actions. Its components were Silksong's components. And still no boss fight played
through, because a boss fight is an integration of several hundred small things — one FSM
variable, one object reference, one collider layer — each able to fail silently and only
in play. Every diagnosis cost a round trip through a human launching the game and
describing what they saw.

**This project deletes that problem rather than solving it.** Silksong's bosses already
work in Silksong. They are not ported, converted, rebuilt or approximated. They are the
game's own content, running the game's own code, in the rooms they were authored in.

## The thing that makes it tractable

Silksong ships its bosses in **their own scenes**, separate from the rooms around them:

```
bellway_01_boss              bone_east_08_boss_beastfly    greymoor_05_boss
bellway_02_boss              bone_east_08_boss_golem       greymoor_08_boss
bellway_03_boss              bone_east_08_boss_golem_rest  hang_04_boss
bellway_04_boss              bonetown_boss                 ward_02_boss
bellway_centipede_arena      cog_dancers_boss
bone_05_boss                 coral_judge_arena
```

Sixteen by that naming convention alone — a full survey will find more, since several
bosses live in their room's main scene instead. They are loaded the ordinary way, by the
game's own code:

```csharp
// SceneAdditiveLoadConditional
loadOp = Addressables.LoadSceneAsync("Scenes/" + SceneNameToLoad, LoadSceneMode.Additive);
```

And Godhome's Pantheon machinery, which Silksong still has in full, is driven by **scene
names**:

```csharp
public class BossScene { public string sceneName; ... }
public class BossSequence : ScriptableObject { BossScene[] bossScenes; ... }
```

So a Pantheon is a list of Silksong scenes. That is the whole idea. `BossSceneController`
already exists to run one arena's lifecycle and end it when its bosses die, and
`BossSequenceController` already exists to chain them.

## What is inherited and already works

From SilksongGodhome, all present in this repo:

* The Godseeker entry on the play-mode menu, revealed through `RecBossRushMode` — the
  boss-rush `StartGameEventTrigger` Silksong already ships.
* A Godhome save slot with its own area art and name.
* Godhome's rooms rebuilt from a baked format: architecture, terrain meshes, colliders,
  camera lock areas, transitions, scene bounds and Hollow Knight's own colour grading.
  17 rooms bake and verify byte-exact.
* Walking between rooms, the bench, the Hall of Gods statues, the Pantheon doors, the
  binding/challenge screen.
* The extraction pipeline: `tools/`, with automatic component-layout derivation, a
  byte-exact FSM parser, tk2d collection and animation rebuilding, and an installer that
  needs nothing but Python.

## What actually has to be built

Roughly, and in order:

1. **A boss survey.** Which Silksong scenes contain a boss, what its `HealthManager` is,
   and how the room signals that the fight is over. `tools/` already has the machinery to
   read Silksong's own scenes; this is a scan, not a port.
2. **Make a Silksong boss room work as a Pantheon arena.** Put a `BossSceneController` in
   it, point it at the boss's `HealthManager`, and let its `OnBossSceneComplete` advance
   the run. Everything on both sides of that already exists.
3. **Getting in and out.** A Pantheon arena needs the hero placed, the room's own entry
   sequence suppressed, and a clean exit on death or victory.
4. **Pantheon rosters.** Which bosses, in what order, across how many Pantheons.
5. **The Hall of Gods.** Statues for Silksong's bosses — art and journal data that
   Silksong already has.

## An open question worth deciding early

Godhome's *rooms* still come from Hollow Knight, so this still needs a copy of it to
build the hub. That is inherited, and it works.

The alternative is a hub built from Silksong's own assets — no Hollow Knight required at
all, and a mod that could be distributed as a normal download rather than as an extractor
you run against your own copy. That is a real trade: Godhome's Atrium is a large part of
why anyone wants this, and giving it up costs the thing's identity. Worth choosing on
purpose rather than by default.

## Build

```bash
dotnet build -c Release SilksongGodhome/SilksongGodhome.csproj
```

Set `GamePath` in `LocalPaths.props` (gitignored) to your Silksong install. The plugin
reads its baked data from a `Godhome` folder beside the DLL, or from resources embedded
in it — see `Rebuild/GodhomeResources.cs`.

To bake Godhome's rooms from your own Hollow Knight:

```bash
python3 tools/extract_godhome.py        # finds both games by itself
python3 tools/verify_baked.py           # every room must read byte-exactly
```

## Ground rules carried over from the last attempt

These were learned the hard way and are worth keeping.

* **Byte-exactness is the test.** A parsed structure is only trusted when the cursor
  lands exactly on the end of its buffer. Every format bug in the previous project was
  caught this way, and a wrong layout costs a skipped component rather than a corrupted
  room.
* **Prefer running the game's own code to imitating it.** Shims are for the debug path.
* **A depth convention belongs to the host game's camera, not to the content.** The last
  bug found in the previous project was faithfully porting Hollow Knight's `BlurPlane`,
  which set Silksong's scene camera far clip plane and clipped the entire room away.
* **Log the state, not the symptom.** `BossTrace` logging every FSM state change was
  worth more than any amount of reasoning about why a boss stood still.

## Licence and content

Ships no game content. Godhome's assets are extracted from your own copy of Hollow
Knight, on your own machine. You need to own both games.
