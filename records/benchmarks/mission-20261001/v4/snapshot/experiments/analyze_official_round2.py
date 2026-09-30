"""Derive round-two evidence from participant replays without enemy orders."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import subprocess

from analyze_official_round1 import ROOT, SDK, analyze, digest


OPPONENTS = {
    "V4_1replay.json": ("뚜띠태하소불고기와멸치두명", "109f2e83"),
    "V4_2replay.json": ("붉은 산호초", "1a938b48"),
    "replay.json": ("어잌후", "2b49c08f"),
    "replay (1).json": ("그래피", "34bca1e9"),
    "replay (2).json": ("신촌을못가", "63440e08"),
    "replay (3).json": ("요미", "6f32639a"),
    "replay (4).json": ("공주", "7b34b928"),
    "replay (5).json": ("참새튀김기", "ad842786"),
    "replay (6).json": ("신촌도 우리땅", "b51fb30a"),
    "replay (7).json": ("tAIger", "bc613bbd"),
    "replay (8).json": ("뉴비들", "bffff573"),
    "replay (9).json": ("니땅내땅", "c4381061"),
    "replay (10).json": ("hyper", "d54af110"),
}

CASES = {
    "V4_2replay.json": {"turns": [19, 20, 21, 22, 23, 26, 32, 50, 54, 122, 134], "building": 5},
    "replay (2).json": {"turns": [20, 21, 22, 23, 24, 31, 33, 40, 58, 67], "building": 5},
    "replay (8).json": {"turns": [13, 14, 15, 16, 17, 22, 27, 45, 81, 136, 149], "building": 1},
    "replay (7).json": {"turns": [94, 130, 148, 153, 156, 157, 158, 159, 160], "building": 0},
    "replay (1).json": {"turns": [44, 80, 120, 160], "building": 5},
    "replay (3).json": {"turns": [63, 140, 156, 157, 158, 159, 160], "building": 0},
}


def distribution(values):
    values = sorted(values)
    return {
        "count": len(values), "min": min(values), "mean": statistics.mean(values),
        "p95_nearest_rank": values[(95 * len(values) + 99) // 100 - 1], "max": max(values),
    }


def intervals(turns, building_id, owner):
    result = []
    start = None
    for i, t in enumerate(turns):
        is_owned = next(b["owner"] for b in t["observation"]["buildings"] if b["id"] == building_id) == owner
        if is_owned and start is None:
            start = i
        if start is not None and (not is_owned or i == len(turns) - 1):
            end = i if is_owned else i - 1
            result.append([start, end])
            start = None
    return result


def enrich(path, site_by_game):
    match = analyze(path)
    raw = json.loads(path.read_text())
    turns = raw["turns"]
    s = match["summary"]
    side = s["side"]
    enemy = "K" if side == "Y" else "Y"
    name, prefix = OPPONENTS[path.name]
    assert s["gameId"].startswith("rolling-game-" + prefix)
    site_match = site_by_game[s["gameId"]]
    assert (site_match["opponent"], site_match["outcome"], site_match["side"]) == (name, s["our_result"], side)
    assert site_match["path"] == str(path.relative_to(ROOT))
    s["opponent_identity"] = {"name": name, "source": "records/official/round2/site-observations.json",
                              "url": site_match["url"], "reference_rank": site_match["opponent_reference_rank"]}
    s["submission_link"] = {
        "status": "site submission #4 filename submission-v3.zip; user identifies local v3; exact uploaded byte hash not available in replay",
        "local_version": "v3", "site_submission_number": 4, "filename": "submission-v3.zip", "zip_hash": None,
        "folder_name_is_version_evidence": False,
    }
    s["first_response_ms"] = turns[1]["observation"]["myResponseMs"]
    s["normal_response_ms"] = distribution([t["observation"]["myResponseMs"] for t in turns[2:]])
    s["timing_limit_violations"] = [
        {"turn": t["turn"], "response_ms": t["observation"]["myResponseMs"], "limit_ms": 3000 if t["turn"] == 1 else 300}
        for t in turns[1:] if t["observation"]["myResponseMs"] > (3000 if t["turn"] == 1 else 300)
    ]
    s["event_counts"] = dict(Counter(e["kind"] for t in turns for e in t["observation"]["events"]))
    s["own_w_production_minus_enemy"] = s["our_production"]["W"] - s["enemy_w_production_inferred_from_equal_w_losses"]
    s["warriors_produced_at_cost_3"] = sum(
        r["own_transition"]["production"]["W"] for r in match["turns"][1:]
        if r["own_transition"]["unit_costs"]["W"] == 3
    )
    s["extra_actual_w_production_spend_relative_to_unit_cost_2"] = s["warriors_produced_at_cost_3"]
    s["economic_control_note"] = (
        "HALL count sum is ownership at production/turn start, not exact earned income. "
        "Combat can neutralize a flag before income; cap/capture spending also matter. "
        "Extra W spend compares actual produced units only, not a holding-ENG counterfactual."
    )
    for kind in ("F", "W", "S"):
        assert s["our_production"].get(kind, 0) - s["our_casualties"].get(kind, 0) == s["final_units"][side][kind]
    leads = [(r["retrospective_scores"][side] - r["retrospective_scores"][enemy], r["turn"]) for r in match["turns"]]
    best, first_best_turn = max(leads, key=lambda x: (x[0], -x[1]))
    s["maximum_retrospective_score_lead"] = {"margin": best, "first_turn": first_best_turn}
    s["first_economic_ownership_loss"] = next((
        {"turn": r["turn"], **c} for r in match["turns"] for c in r["ownership_changes"]
        if c["from"] == side and c["type"] in ("HALL", "ENG", "HOSPITAL")
    ), None)
    if s["first_economic_ownership_loss"]:
        first = s["first_economic_ownership_loss"]
        recovery = next((r["turn"] for r in match["turns"] if r["turn"] > first["turn"]
                         and any(c["id"] == first["id"] and c["to"] == side for c in r["ownership_changes"])), None)
        first["first_recovery_turn"] = recovery
        first["first_unowned_interval_length"] = (recovery if recovery is not None else len(turns)) - first["turn"]
    s["economic_building_ownership_intervals"] = [
        {"id": b["id"], "type": b["type"], "x": b["x"], "y": b["y"],
         "intervals_inclusive": {t: intervals(turns, b["id"], t) for t in ("Y", "K", "N")}}
        for b in turns[0]["observation"]["buildings"] if b["type"] in ("HALL", "ENG", "HOSPITAL")
    ]
    s["phases"] = []
    for start, end in ((1, 30), (31, 80), (81, 130), (131, 160)):
        rows = [r for r in match["turns"] if start <= r["turn"] <= end]
        if not rows:
            continue
        prod, dead = Counter(), Counter()
        for r in rows:
            prod.update(r["own_transition"]["production"])
            dead.update(r["own_transition"]["casualties"])
        s["phases"].append({"start": start, "end": rows[-1]["turn"], "own_production": prod,
                            "own_casualties": dead, "enemy_w_production": sum(r["own_transition"]["enemy_w_production_inferred"] for r in rows),
                            "end_scores_retrospective": rows[-1]["retrospective_scores"]})
    case = CASES.get(path.name)
    if case:
        case_records = []
        for i in case["turns"]:
            turn = turns[i]
            b = next(b for b in turn["observation"]["buildings"] if b["id"] == case["building"])
            case_records.append({
                "turn": i, "building": b, "own_command": turn["command"],
                "legal_input": turns[i - 1]["observation"], "observed_after": turn["observation"],
                "derived": match["turns"][i],
                "units_within_manhattan_3_of_case_building": [u for u in turn["observation"]["units"]
                    if abs(u[2] - b["x"]) + abs(u[3] - b["y"]) <= 3],
            })
        match["case_evidence"] = case_records
    return match


def write_markdown(result, path):
    agg = result["aggregate"]
    lines = [
        "# 두 번째 공식 경기 리플레이 분석",
        "",
        "2026-09-28 10:00 평가의 13경기는 **9승 4패**, 모두 연세(Y) 진영이다. 사이트에서 확인한 게임 ID와 원본 13개가 일치한다. "
        "`V4_replay`는 수집 폴더명이며 로컬 v4의 실전 결과가 아니다. 사이트 제출 #4의 파일명은 `submission-v3.zip`, 사용자도 로컬 v3 사용을 확인했다. 업로드 ZIP 바이트 해시는 리플레이에 없다.",
        "",
        "핵심은 **후방 경제 거점에 접근하는 F를 차단하고, 중립화 뒤 F를 보내 복구하는 능력**과 **막판 점령 배분**이다. "
        "세 대패는 앞서 점수 우위를 얻고도 경제 거점을 잃은 뒤 W 생산 격차가 누적됐다. 다른 한 패배는 경제가 대등해도 마지막 두 턴에 역전됐다. "
        "지표만으로 한 행동이 전체 패배의 유일한 원인이라고 단정하지 않는다.",
        "",
        f"공식 엔진으로 우리 생산·이동 {agg['own_spawn_move_transitions_checked']:,}턴을 검증했다. 상대 명령이 없어 전체 경기 재현이나 승리 반사실 검증은 아니다. "
        f"명령 상태는 전부 `ok`, 관측된 시간 초과는 0건이다. 일반 턴 최대 {agg['normal_response_ms']['max']}ms, 첫 응답 최대 {agg['first_response_ms']['max']}ms로 각각 300/3000ms 한도 안이다.",
        "",
        "| 상대 | 결과 | 종료 턴 | 최종 점수 Y:K | W 생산 Y:K | F 생산/사망 Y | ENG 보유 턴 Y:K | HALL 보유 합 Y:K |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for m in result["matches"]:
        s = m["summary"]
        e, score = s["economy"], s["final_scores_reconstructed"]
        lines.append(f"| {s['opponent_identity']['name']} | {'승' if s['our_result']=='win' else '패'} | {s['turn_count']} | {score['Y']}:{score['K']} | "
                     f"{s['our_production']['W']}:{s['enemy_w_production_inferred_from_equal_w_losses']} | {s['our_production']['F']}/{s['our_casualties']['F']} | "
                     f"{e['Y']['turns_with_eng_at_production']}:{e['K']['turns_with_eng_at_production']} | {e['Y']['hall_count_sum_at_turn_start']}:{e['K']['hall_count_sum_at_turn_start']} |")
    lines.extend([
        "",
        "ENG/HALL은 생산 직전 소유 상태를 센 값이다. HALL은 두 건물을 합치므로 종료 턴을 넘을 수 있다. 실제 수입에는 전투 중립화·자원 상한·점령 지출이 작용하므로 이 수치를 곧바로 획득 자원으로 바꾸지 않았다. "
        "상대 W 생산은 양쪽 W가 전투에서 같은 수만큼 제거되는 규칙과 공개 병력 수로 정확히 역산했다. 상대 F 생산·명령은 복원하지 않았다.",
        "",
        "## 네 패배의 관측 근거",
        "",
        "**붉은 산호초 — `V4_2replay.json`, 134턴 0:41.** 공학관(4,12)으로 상대 F1이 t19 (7,12) → t20 (6,12) → t21 (5,12) → t22 (4,12)로 접근한다. "
        "t22에 빈 공학관을 중립화하고 t23에 빼앗는다. 이 거점에서 우리 병력 사상은 없었다. 당시 전체 점수는 t21 22:14, t26에는 31:8까지 앞서지만 "
        "공학관 복구는 t32이고 이후에도 반복해서 잃는다. t54에는 HALL도 상실한다. W 생산은 535:773, 최종 병력은 W3:241이다. "
        "t122 병원 상실은 이 경제·생산 열세보다 훨씬 늦다. 첫 경제 손실 전에 보이는 침투를 차단하지 못한 사례이며, t22가 최초의 최적 정책 이탈이었다는 증명은 아니다.",
        "",
        "**신촌을못가 — `replay (2).json`, 67턴 0:35.** 상대 F1은 t20 (0,12) → t21 (0,11) → t22 (0,10) → t23 공학관(0,9)에 들어와 중립화한다. "
        "우리 W1이 t24에 (1,9)에서 공학관으로 이동하지만 우리 F가 없어 공학관 소유권은 t33에야 회복된다. 별도 상대 F가 t24 HALL(1,1)도 중립화하고 t31까지 복구되지 않는다. "
        "t22 21:13으로 앞섰다가 t23 16:16, t24 14:16이 된다. W 생산 272:383, ENG 할인 보유는 28:62턴이다. "
        "전투병으로 침입자를 쫓는 행동과 깃발병으로 경제 거점을 재점령하는 행동을 구분해 평가해야 한다.",
        "",
        "**뉴비들 — `replay (8).json`, 149턴 0:39.** 상대 F1은 t13 (4,10) → t14 (3,10) → t15 (2,10) → t16 HALL(1,10)에 들어온다. "
        "t16 우리 병력 사상은 없고, 학생회관이 중립화된다. t17 상대가 획득하는 동안 우리는 26:13으로 점수에서 앞선다. "
        "HALL 보유 합은 32:224, W 생산은 651:909가 된다. ENG는 131:148턴으로 상대적으로 비슷하다. "
        "이 경기는 공학관만 강화하는 수정의 반례이며, 저점수 HALL의 지속 수입과 복구·유지 역할이 중요한 연구 대상이다.",
        "",
        "**tAIger — `replay (7).json`, 160턴 15:17.** ENG 156:156턴, HALL 합 152:152, W 생산 815:823으로 경제가 대등하다. "
        "t94 28:7 우위, t156–157 20:17, t158 17:14에서 t159 광장(3점)·WATCH(2점)를 잃는다. "
        "STATION 3점을 얻지만 상대도 DEPOT 3점을 얻어 15:17이 되고 t160에는 소유권 변화가 없다. 누적 점령 점수는 2941:2296으로 앞서도 최종 점수가 우선이어서 패배한다. "
        "t160에는 병원(0,7)에 W19를 생산했으나 실제 결과에서 점수 회복으로 이어지지 않았다. 이 행동만 바꾸면 이긴다는 뜻은 아니며, "
        "남은 턴 내 점수 변화에 도달하는 F/W 동시 배분과 여러 거점의 손실 방지가 별도 과제다.",
        "",
        "위 접근 경로·상대 병력·건물 소유권은 해당 시점에 합법적으로 보이는 정보다. 전체 점수 재구성은 이후 공개 점수와 대칭성을 이용한 사후 분석이며, "
        "JSON의 `legal_scores_as_of_turn`과 별도로 저장했다. 네 패배 모두 위 핵심 경제 손실/종반 사례 시점에는 전체 건물 점수를 대칭성으로 추론할 수 있었다. "
        "상대 명령이 없으므로 특정 수비 수가 승리를 보장한다고 주장하지 않는다.",
        "",
        "## 승리 사례가 제한하는 결론",
        "",
        "- 그래피전은 ENG 94:151턴, W 생산 704:802로 열세여도 29:8로 승리했다. 경제 우위가 승리의 필요조건이라는 결론은 틀리다. "
        "경제 수비를 무조건 고정하고 공격을 포기하는 수정은 이 경기와 함께 평가해야 한다.",
        "- 요미전은 W 생산 864:863으로 거의 같고 21:18로 이겼다. tAIger 접전 패배와 함께 종반 목적·점령 배분 비교군으로 보존한다.",
        "- hyper·공주전은 상대 W 생산이 각각 0·10이다. 이 두 승리만 제외하면 7승 4패다. 이는 상대 강도를 설명하는 참고 분류이며, 공식 9승 4패나 보정 점수를 다시 계산한 값이 아니다.",
        "",
        "## 다음 후보의 검증 항목",
        "",
        "1. 경제 거점에 들어올 수 있는 상대 F를 2–3턴 먼저 예측하고 경로 차단과 거점 대기를 비교한다. 단순 추격·모든 거점 상시 수비·현재 v3/v4를 제거 실험 기준선으로 둔다.",
        "2. W 차단 이후에도 중립 경제 건물은 복구되지 않는다는 점을 반영해 F 재점령 임무를 분리한다. 수비 비용, 복구 시간, HALL·ENG 유지 시간과 승률을 함께 측정한다.",
        "3. 마지막 5–10턴은 도달 가능한 점수 변화와 상대 동시 점령을 직접 비교한다. 단일 거점 방어, 여러 거점 공동 할당, 기존 탐색을 별도 후보로 둔다.",
        "4. 세 후방 침투형과 다수 F 종반형을 고정 상대 집단에 추가하고, 경제 열세에서도 이긴 그래피 유형을 회귀 반례로 유지한다. "
        "이 리플레이를 본 뒤 만든 후보의 검증에는 별도 새 맵을 사용한다. 과거 내부 승률 +10%p가 새 리더보드에 그대로 전이된다고 보지 않는다.",
        "",
        "원본 해시·경기 ID·엔진/분석 소스 해시·전 턴 파생 결과·주요 턴의 합법 입력과 실제 명령은 [replay-analysis.json](replay-analysis.json)에 있다. "
        "사이트의 제출·상대·경기 수 확인은 [site-observations.json](site-observations.json), 원본 목록은 [source-manifest.json](source-manifest.json)에 있다. "
        "실행: `PYTHONDONTWRITEBYTECODE=1 python experiments/analyze_official_round2.py`. 원본은 수정하지 않는다.",
        "",
    ])
    path.write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=ROOT / "V4_replay")
    parser.add_argument("--output", type=Path, default=ROOT / "records/official/round2/replay-analysis.json")
    args = parser.parse_args()
    paths = sorted(args.input.resolve().glob("*.json"))
    assert {p.name for p in paths} == set(OPPONENTS)
    site_path = ROOT / "records/official/round2/site-observations.json"
    manifest_path = ROOT / "records/official/round2/source-manifest.json"
    site = json.loads(site_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    site_by_game = {m["game_id"]: m for m in site["matches"]}
    initial_hashes = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    assert initial_hashes == {f["path"]: f["sha256"] for f in manifest["files"]}
    matches = [enrich(p, site_by_game) for p in paths]
    summaries = [m["summary"] for m in matches]
    assert len({s["gameId"] for s in summaries}) == 13
    assert {s["gameId"] for s in summaries} == set(site_by_game)
    assert {s["side"] for s in summaries} == {"Y"}
    assert len({s["evaluationId"] for s in summaries}) == 1
    assert Counter(s["our_result"] for s in summaries) == {"win": 9, "loss": 4}
    assert not any(s["timing_limit_violations"] for s in summaries)
    rows = [r for m in matches for r in m["turns"][1:]]
    agg = {
        "match_count": len(matches), "results": dict(Counter(s["our_result"] for s in summaries)),
        "side_counts": dict(Counter(s["side"] for s in summaries)),
        "own_spawn_move_transitions_checked": sum(s["own_spawn_move_transitions_checked"] for s in summaries),
        "command_status_counts": dict(sum((Counter(s["command_status_counts"]) for s in summaries), Counter())),
        "first_response_ms": distribution([s["first_response_ms"] for s in summaries]),
        "normal_response_ms": distribution([r["response_ms"] for r in rows if r["turn"] > 1]),
        "all_response_ms": distribution([r["response_ms"] for r in rows]),
        "timing_limit_violation_count": 0,
        "win_rate_in_this_complete_site_round": 9 / 13,
    }
    source_files = [Path(__file__), site_path, manifest_path, ROOT / "experiments/analyze_official_round1.py", SDK / "engine/pipeline.py",
                    SDK / "engine/state.py", SDK / "runner/protocol.py", SDK / "config/balance.json", SDK / "docs/rulebook.md"]
    result = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "replay_origin_commit": subprocess.check_output(["git", "rev-parse", "d766387a"], cwd=ROOT, text=True).strip(),
        "analysis_sources": {str(p.relative_to(ROOT)): digest(p) for p in source_files},
        "engine_game_commit": json.loads((SDK / "docs/platform-sdk-provenance.json").read_text())["gameCommit"],
        "command": "PYTHONDONTWRITEBYTECODE=1 python experiments/analyze_official_round2.py",
        "scope": {
            "complete_round": "13 files match all 13 games on the 2026-09-28 10:00 site evaluation; independently checked by primary agent",
            "site_checked_by": "primary agent; opponent-name mapping supplied by game ID",
            "site_evaluation_display": "2026-09-28 10:00 KST", "site_rank": 19, "site_adjusted_score_display": 66.2,
            "observations": "participant view: public units/resources/ownership; enemy commands absent",
            "score_reconstruction": "later revealed building scores plus exact 180-degree pairs; legal per-turn scores stored separately",
            "transition_verification": "own spawn/move only; all own casualties derived from after-movement versus actual survivors",
            "counterfactual": "none; temporal associations and exact local stage evidence are not full-game causal proof",
            "leaderboard": "adjusted score is site reported, not calculated from this analyzer or equated to raw win rate",
            "version": "site submission #4/local v3, not local v4; uploaded ZIP hash unverified",
        },
        "original_hashes": initial_hashes, "aggregate": agg, "matches": matches,
    }
    assert initial_hashes == {str(p.relative_to(ROOT)): digest(p) for p in paths}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    write_markdown(result, args.output.with_suffix(".md"))
    print(json.dumps({"output": str(args.output), "aggregate": agg}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
