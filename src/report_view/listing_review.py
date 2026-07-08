from __future__ import annotations

import re
from typing import Any


def _listing_review_details(shared: Any, reason: object, evidence: object, action: object = "") -> dict[str, str]:
    reason_text = str(reason or "")
    evidence_text = str(evidence or "")
    merged = f"{reason_text}；{evidence_text}"
    signals: list[str] = []
    directions: list[str] = []
    questions: list[str] = []
    materials: list[str] = []
    temp_actions: list[str] = []

    def add(items: list[str], *values: str) -> None:
        for value in values:
            if value and value not in items:
                items.append(value)

    if "推荐报价率" in merged or "Buy Box" in merged:
        add(signals, "推荐报价率低于 95% 或推荐报价不稳定")
        add(directions, "疑似 Buy Box / 推荐报价不稳定")
        add(questions, "当前是否丢购物车/推荐报价？", "售价是否高于同类竞品？", "配送时效是否比竞品慢？", "是否有库存或配送异常？", "是否被跟卖/竞争报价影响？")
        add(materials, "重点发 Buy Box / 推荐报价截图", "重点发前三竞品价格和配送截图", "重点发当前售价、Coupon、配送时效")
        add(temp_actions, "先不要加广告预算，优先确认推荐报价和价格")

    if "traffic_sales" in merged and ("转化率" in merged or "下降" in merged):
        add(signals, "页面成交率下降")
        add(directions, "疑似 Listing 承接弱或价格/Coupon 竞争力不足")
        add(questions, "主图是否一眼能看出产品核心卖点？", "标题是否和主要搜索词匹配？", "价格是否高于前三竞品？", "是否有 Coupon，竞品是否有 Coupon？", "评分和评论数是否弱于竞品？", "差评集中在哪些问题？")
        add(materials, "重点发竞品价格 / Coupon 对比", "重点发最近差评截图", "重点发首屏与前三竞品首屏对比")
        add(temp_actions, "广告先不加预算；相关高花费 0 单词先降竞价；等页面判断后再决定改图/改价/Coupon")

    if ("点击" in merged and "订单 0" in merged) or "广告无单" in merged:
        add(signals, "广告点击有样本但订单弱或 0 单")
        add(directions, "疑似广告流量不准，不一定是 Listing 问题")
        add(questions, "搜索词是否和产品强相关？", "是否有宽泛词、低价词、材质不符词、尺寸不符词？", "出单词和花费词是否一致？", "是否某个广告活动带来大量无效点击？")
        add(materials, "重点发高花费 0 单搜索词列表", "重点发对应广告活动 / 广告组截图")
        add(temp_actions, "明显不相关词否定精准；相关泛词先降竞价；核心词不直接否")

    if "搜索查询" in merged or "SQP" in merged or "展示" in merged and "加购" in merged:
        add(signals, "搜索漏斗展示/点击/加购/购买存在下降或漏斗异常")
        add(directions, "疑似搜索漏斗下降，可能是排名、价格、竞品、页面承接共同影响")
        add(questions, "核心关键词自然排名是否下降？", "竞品是否降价或加 Coupon？", "价格/评分/评论是否失去竞争力？", "主图是否相比竞品弱？", "是否有断货、配送变慢、评价变差？")
        add(materials, "重点发搜索词周对比截图", "重点发核心关键词搜索结果页截图", "重点发竞品价格 / Coupon 对比")
        add(temp_actions, "不要只靠否词解决；先查排名、竞品、价格和页面")

    if "ACOS" in merged:
        add(signals, "有订单但 ACOS 高于目标或近期 ACOS 升高")
        add(directions, "疑似产品有市场，但广告效率变差")
        add(questions, "出单词 ACOS 是否过高？", "高花费词是否过宽？", "是否有低价无效搜索词？", "价格和利润是否允许继续投放？")
        add(materials, "重点发出单词 ACOS 列表", "重点发高花费 0 单词列表", "重点发产品毛利 / 目标 ACOS")
        add(temp_actions, "保留出单词；高 ACOS 出单词小幅降竞价；无关词否定精准；不要直接关广告")

    if not signals:
        add(signals, reason_text or "广告/销量/增强数据出现转化疑点")
    if not directions:
        add(directions, "疑似广告效率变差，需结合页面、价格、竞品和搜索词人工确认")
    if not questions:
        add(questions, "主要搜索词是否强相关？", "价格、Coupon、评分、评论数是否弱于前三竞品？", "主图和标题是否能承接当前流量？")
    if not materials:
        add(materials, "重点发最可疑搜索词列表", "重点发竞品价格 / Coupon 对比")
    if not temp_actions:
        add(temp_actions, shared.LISTING_TEMP_ACTION)

    return {
        "异常信号": "；".join(signals[:5]),
        "初步方向": "；".join(directions[:3]),
        "需要人工确认": "；".join(questions[:6]),
        "发给 ChatGPT 的材料": "；".join(materials[:6]),
        "产品专属下一步": "；".join(temp_actions[:3]) or str(action or shared.LISTING_TEMP_ACTION),
    }


def _extract_number_after(shared: Any, text: str, label: str) -> float | None:
    match = re.search(rf"{re.escape(label)}\s*([0-9]+(?:\.[0-9]+)?)", str(text or ""))
    if not match:
        return None
    return shared._to_float(match.group(1))


def _compact_money_from_evidence(shared: Any, text: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}\s*([£$€][0-9]+(?:\.[0-9]+)?)", str(text or ""))
    return match.group(1) if match else "N/A"


def _recent_7d_listing_metrics(shared: Any, evidence: str) -> tuple[float | None, float | None, str]:
    text = str(evidence or "")
    match = re.search(
        r"近7天点击\s*([0-9]+(?:\.[0-9]+)?)；订单\s*([0-9]+(?:\.[0-9]+)?)；花费\s*([£$€][0-9]+(?:\.[0-9]+)?)",
        text,
    )
    if not match:
        return None, None, "N/A"
    return shared._to_float(match.group(1)), shared._to_float(match.group(2)), match.group(3)


def _product_line_hint(shared: Any, product_name: object, sku: object = "", asin: object = "") -> str:
    text = f"{product_name or ''} {sku or ''} {asin or ''}".lower()
    if any(token in text for token in ["desk lamp", "led lamp", "reading lamp"]):
        return "demo desk lamp"
    if any(token in text for token in ["notebook", "spiral", "journal"]):
        return "demo notebook"
    if any(token in text for token in ["cable ties", "wire ties", "cable management"]):
        return "demo cable ties"
    return "该产品"


def _group_records_by_asin(shared: Any, records: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for record in records:
        asin = str(record.get("asin") or "").strip()
        if asin:
            grouped.setdefault(asin, []).append(record)
    return grouped


def _sum_record_metric(shared: Any, records: list[dict], key: str) -> float:
    total = 0.0
    for record in records:
        value = shared._to_float(record.get(key))
        if value is not None:
            total += value
    return total


def _first_record_metric(shared: Any, records: list[dict], key: str) -> float | None:
    for record in records:
        value = shared._to_float(record.get(key))
        if value is not None:
            return value
    return None


def _enhanced_listing_signals(shared: Any, traffic_records: list[dict], query_records: list[dict]) -> dict[str, list[str]]:
    signals: list[str] = []
    directions: list[str] = []
    questions: list[str] = []
    materials: list[str] = []
    next_steps: list[str] = []

    if traffic_records:
        recent_cr = _first_record_metric(shared, traffic_records, "recent_conversion_rate")
        prior_cr = _first_record_metric(shared, traffic_records, "prior_conversion_rate")
        cr_change = _first_record_metric(shared, traffic_records, "conversion_rate_change_pct")
        recent_offer = _first_record_metric(shared, traffic_records, "recent_featured_offer_rate")
        prior_offer = _first_record_metric(shared, traffic_records, "prior_featured_offer_rate")
        recent_views = _first_record_metric(shared, traffic_records, "recent_featured_offer_page_views")
        prior_views = _first_record_metric(shared, traffic_records, "prior_featured_offer_page_views")
        views_change = _first_record_metric(shared, traffic_records, "featured_offer_page_views_change_pct")

        if recent_offer is not None and recent_offer < 0.95:
            prior_text = f"，前期 {shared._format_percent(prior_offer)}" if prior_offer is not None else ""
            signals.append(f"增强数据：推荐报价率 {shared._format_percent(recent_offer)}{prior_text}，先查 Buy Box/价格/配送")
            directions.append("增强数据指向推荐报价风险，不要先把问题归到主图/A+")
            questions.extend(["当前是否丢推荐报价？", "售价和配送是否弱于前三竞品？"])
            materials.append("重点发 Buy Box / 推荐报价截图")
            next_steps.append("先核查 Buy Box/配送；确认异常后再决定调价或调广告")
        elif recent_cr is not None and prior_cr is not None and cr_change is not None and cr_change <= -0.2:
            signals.append(f"增强数据：页面成交率从 {shared._format_percent(prior_cr)} 到 {shared._format_percent(recent_cr)}，变化 {shared._format_percent(cr_change)}")
            directions.append("增强数据指向页面/价格承接变弱，优先查价格、Coupon、评价和竞品")
            questions.extend(["转化率下降期间价格/Coupon 是否变化？", "前三竞品是否降价或加 Coupon？"])
            materials.append("重点发页面成交率截图")
            next_steps.append("先补价格/Coupon/竞品截图；确认差异后再小改页面或价格")
        elif views_change is not None and views_change <= -0.2:
            recent_text = shared._format_count(recent_views) if recent_views is not None else "N/A"
            prior_text = shared._format_count(prior_views) if prior_views is not None else "N/A"
            signals.append(f"增强数据：推荐报价浏览量从 {prior_text} 到 {recent_text}，变化 {shared._format_percent(views_change)}")
            directions.append("增强数据更像流量入口变弱，先查广告流量和搜索排名")
            questions.extend(["核心词曝光/排名是否下降？", "广告预算或竞价是否被压低？"])
            materials.append("重点发页面浏览量趋势截图")
            next_steps.append("先复查核心词曝光/排名和广告覆盖；预算暂不扩")
        elif recent_cr is not None or recent_offer is not None:
            signals.append(
                "增强数据："
                + (f"页面成交率 {shared._format_percent(recent_cr)}" if recent_cr is not None else "")
                + ("，" if recent_cr is not None and recent_offer is not None else "")
                + (f"推荐报价率 {shared._format_percent(recent_offer)}" if recent_offer is not None else "")
            )
            directions.append("增强数据没有显示明显 Buy Box 或转化断点，优先从广告词/ASIN 定向找低效来源")

    if query_records:
        impressions = _sum_record_metric(shared, query_records, "query_impressions")
        prior_impressions = _sum_record_metric(shared, query_records, "prior_query_impressions")
        clicks = _sum_record_metric(shared, query_records, "query_clicks")
        carts = _sum_record_metric(shared, query_records, "query_cart_adds")
        purchases = _sum_record_metric(shared, query_records, "query_purchases")
        prior_purchases = _sum_record_metric(shared, query_records, "prior_query_purchases")
        if carts > 0 and purchases == 0:
            signals.append(f"增强数据：搜索漏斗有加购 {int(carts)} 但购买 0，重点查价格/Coupon/配送")
            directions.append("增强数据指向加购后流失，不是单纯否词能解决")
            questions.extend(["加购后是否因价格、Coupon 或配送流失？", "竞品同词下是否更便宜或更快？"])
            materials.append("重点发搜索漏斗加购/购买截图")
            next_steps.append("先对比价格/Coupon/配送；确认差异后再处理广告扩量")
        elif prior_purchases > 0 and purchases < prior_purchases:
            signals.append(f"增强数据：搜索漏斗购买从 {int(prior_purchases)} 到 {int(purchases)}，搜索漏斗变弱")
            directions.append("增强数据指向搜索漏斗下降，先查排名、竞品价格和页面点击承接")
            questions.extend(["核心关键词自然排名是否下降？", "竞品是否在同词下促销？"])
            materials.append("重点发搜索词周对比截图")
            next_steps.append("核心词先不否；补搜索结果页截图，明天复查搜索漏斗购买和广告订单")
        elif prior_impressions > 0 and impressions < prior_impressions * 0.8:
            signals.append(f"增强数据：搜索漏斗展示从 {int(prior_impressions)} 到 {int(impressions)}，搜索入口变少")
            directions.append("增强数据指向曝光/排名问题，优先查搜索结果页和广告覆盖")
            questions.append("核心词自然位或广告位是否下滑？")
            materials.append("重点发核心词搜索结果页截图")
            next_steps.append("先查排名/广告覆盖；不急着改 Listing 或加预算")
        elif impressions or clicks or purchases:
            signals.append(f"增强数据：搜索漏斗展示 {int(impressions)} / 点击 {int(clicks)} / 加购 {int(carts)} / 购买 {int(purchases)}")

    return {
        "signals": signals,
        "directions": directions,
        "questions": questions,
        "materials": materials,
        "next_steps": next_steps,
    }


def _unique_limited(shared: Any, items: list[str], limit: int) -> list[str]:
    deduped: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in deduped:
            deduped.append(text)
        if len(deduped) >= limit:
            break
    return deduped


def _rewrite_listing_review_copy(shared: Any, rows: list[dict[str, str]], search_queue: list[dict[str, str]], analysis_payload: dict | None = None) -> list[dict[str, str]]:
    queue_by_key: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for item in search_queue:
        key = (
            str(item.get("marketplace") or "").upper(),
            str(item.get("sku") or ""),
            str(item.get("asin") or ""),
        )
        queue_by_key.setdefault(key, []).append(item)
    traffic_by_asin = _group_records_by_asin(shared, (analysis_payload or {}).get("custom_traffic_sales", []))
    query_by_asin = _group_records_by_asin(shared, (analysis_payload or {}).get("custom_search_query_performance", []))

    rewritten: list[dict[str, str]] = []
    for row in rows:
        marketplace = str(row.get("marketplace") or "").upper()
        sku = str(row.get("SKU") or row.get("sku") or "")
        asin = str(row.get("ASIN") or row.get("asin") or "")
        product = str(row.get("产品") or row.get("product_name") or "")
        reason = str(row.get("主因") or "")
        evidence = str(row.get("关键证据") or "")
        product_line = _product_line_hint(shared, product, sku, asin)
        related_terms = queue_by_key.get((marketplace, sku, asin), [])
        visible_terms = [term for term in related_terms if term.get("html_visible") != "否"]
        bid_terms = [term for term in visible_terms if "降竞价" in str(term.get("suggested_action") or "")]
        negative_terms = [term for term in visible_terms if str(term.get("suggested_action") or "") == "否定精准"]
        core_terms = [term for term in visible_terms if str(term.get("relevance_level") or "") in {"核心相关", "已转化"} or "核心" in str(term.get("reason") or "")]
        asin_terms = [term for term in visible_terms if str(term.get("relevance_level") or "") == "ASIN定向"]
        enhanced = _enhanced_listing_signals(shared, traffic_by_asin.get(asin, []), query_by_asin.get(asin, []))

        clicks14 = _extract_number_after(shared, evidence, "近14天产品级广告点击") or _extract_number_after(shared, evidence, "近14天广告点击")
        ad_orders14 = _extract_number_after(shared, evidence, "广告订单")
        spend14 = _compact_money_from_evidence(shared, evidence, "广告花费")
        total14 = _extract_number_after(shared, evidence, "总单")
        clicks7, orders7, spend7 = _recent_7d_listing_metrics(shared, evidence)

        signals: list[str] = []
        signals.extend(enhanced["signals"])
        if "近7天广告无单" in reason:
            signals.append("近7天广告没有出单，但总单不是 0，先看广告承接而不是直接判 Listing 崩")
        if "近7天转化恶化" in reason or "近7天 ACOS 升高" in reason:
            signals.append(f"近7天效率变差：点击 {int(clicks7 or 0)}、广告订单 {int(orders7 or 0)}、花费 {spend7}")
        if "14天 ACOS 高于目标" in reason or "ACOS" in reason:
            signals.append(f"近14天广告有效果但偏贵：点击 {int(clicks14 or 0)}、广告订单 {int(ad_orders14 or 0)}、花费 {spend14}")
        if total14 and total14 >= 5:
            if enhanced["signals"]:
                signals.append(f"广告背景：近14天总单 {int(total14)}，产品仍有需求，增强数据优先用于判断原因")
            else:
                signals.append(f"仅广告背景：近14天总单 {int(total14)}，产品仍有需求；缺少增强信号时再查广告效率和竞品压力")
        if bid_terms:
            signals.append(f"有 {len(bid_terms)} 个词/ASIN 达到降竞价阈值")
        if negative_terms:
            signals.append(f"有 {len(negative_terms)} 个明显不相关词可否定")
        if not signals:
            signals.append(row.get("异常信号") or reason or "广告效率出现异常")

        directions: list[str] = []
        directions.extend(enhanced["directions"])
        if negative_terms:
            directions.append("更像流量不准：先处理明显不相关词")
        if bid_terms and core_terms:
            directions.append("核心词有点击但效率偏弱：先降竞价，不急着否词")
        if asin_terms and not negative_terms:
            directions.append("ASIN 定向带来无效点击：优先看投放对象是否匹配")
        if "ACOS" in reason and total14 and total14 > 0 and not enhanced["directions"]:
            directions.append("仅从广告数据看：产品能出单，但广告效率偏贵；需要增强数据或竞品截图确认原因")
        if "近7天" in reason:
            directions.append("近期波动优先查价格、Coupon、配送和竞品动作")
        if not directions:
            directions.append("先判断是流量不准，还是页面/价格承接变弱")

        questions: list[str] = []
        questions.extend(enhanced["questions"])
        if bid_terms or negative_terms or asin_terms:
            questions.append("这几个花费词/ASIN 和产品是否强相关？")
            questions.append("出单词和花费词是不是同一批？")
        if "ACOS" in reason:
            questions.append("出单词 ACOS 是整体偏高，还是少数词拖累？")
            questions.append("当前售价和 Coupon 是否比前三竞品弱？")
        if "近7天" in reason:
            questions.append("最近 7 天是否改过价格、Coupon、配送、广告预算或竞品有促销？")
        questions.append(f"{product_line} 的主图首屏是否能立刻说明用途/尺寸/套装数量？")
        questions.append("评分、评论数、配送时效是否明显落后前三竞品？")

        materials: list[str] = []
        materials.extend(enhanced["materials"])
        if bid_terms:
            sample = "、".join(str(term.get("search_term_or_target") or "") for term in bid_terms[:3])
            materials.append(f"重点发这些降竞价词截图：{sample}")
        if negative_terms:
            sample = "、".join(str(term.get("search_term_or_target") or "") for term in negative_terms[:3])
            materials.append(f"重点发疑似无关词截图：{sample}")
        materials.append(f"发 {product_line} 自己页面首屏 + 前三竞品首屏")
        if "ACOS" in reason:
            materials.append("发出单词和高花费 0 单词列表")
        if "近7天" in reason:
            materials.append("发最近 7 天价格/Coupon/广告改动记录")

        specific_steps: list[str] = []
        if negative_terms:
            specific_steps.append("只否明显不相关词；相关词和核心词先不否")
        if bid_terms:
            specific_steps.append("只按复制区分档降竞价；不扩大预算，明天复查订单/ACOS")
        if enhanced["next_steps"]:
            specific_steps = [*enhanced["next_steps"], *specific_steps]
        if not specific_steps:
            if visible_terms:
                specific_steps.append("只处理复制区明确动作；观察词不动，低优先级看 Excel")
            else:
                specific_steps.append("先补页面/竞品截图；人工确认前不改 Listing")

        if enhanced["directions"]:
            direction_summary = enhanced["directions"][0]
        elif negative_terms:
            direction_summary = "流量不准优先，先处理明显无关词"
        elif bid_terms:
            direction_summary = "核心/相关词效率偏弱，先降竞价再观察"
        elif "ACOS" in reason:
            direction_summary = "广告偏贵，先看出单词和竞品价格"
        else:
            direction_summary = directions[0] if directions else "先补关键截图再判断原因"

        updated = dict(row)
        updated.update(
            {
                "异常信号": "；".join(_unique_limited(shared, signals, 3)),
                "初步方向": direction_summary,
                "需要人工确认": "；".join(_unique_limited(shared, questions, 2)),
                "发给 ChatGPT 的材料": "；".join(_unique_limited(shared, materials, 2)),
                "产品专属下一步": "；".join(_unique_limited(shared, specific_steps, 2)),
            }
        )
        rewritten.append(updated)
    return rewritten
