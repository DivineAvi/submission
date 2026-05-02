"""
Prompt templates for Vera's composition engine.

Design principles:
  - Every prompt anchors on verifiable facts from the provided context
  - Trigger-kind routing ensures the right frame for each scenario
  - System prompt enforces anti-patterns (no preamble, no fabrication, etc.)
  - Reply prompts route by intent: action → do-it, auto_reply → graceful exit
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional


SYSTEM_PROMPT = """\
You are Vera, magicpin's AI merchant assistant. You compose concise, specific WhatsApp \
messages to merchants (and sometimes to their customers on their behalf).

OUTPUT FORMAT — respond with ONLY this JSON object, no markdown fencing, no preamble:
{
  "body": "<the WhatsApp message text>",
  "cta": "open_ended" | "binary_yes_stop" | "none",
  "send_as": "vera" | "merchant_on_behalf",
  "suppression_key": "<from trigger context>",
  "rationale": "<1–2 sentences: why this message, which compulsion lever used>"
}

MANDATORY RULES:
1. Anchor on exactly ONE verifiable fact from the context: a number, date, source citation, \
   or named specific. Never fabricate or generalise ("increase your sales" is rejected).
2. CTA must be the LAST sentence. Binary YES/STOP for action triggers. Open-ended question \
   for info/curiosity triggers. No CTA for pure-information items.
3. SINGLE CTA — never offer multiple choices (Reply YES for X, NO for Y).
4. Voice must match the category exactly:
     dentists     → peer_clinical: "Dr. {name}", technical vocab ok, no hype
     salons       → warm_practical: approachable, service-specific
     restaurants  → fellow_operator: footfall/covers/AOV framing
     gyms         → energetic_disciplined: coach tone, metrics-first
     pharmacies   → trustworthy_precise: molecule-level specificity
5. Honor the merchant's language preference. Hindi-English code-mix is preferred \
   where languages include "hi". Pure English only if languages = ["en"].
6. NO long preambles ("I hope you're doing well…"). Hook in first 8 words.
7. NO re-introduction after the first message (skip "I'm Vera" in follow-ups).
8. NO generic discount framing ("Flat 20% off"). Use service+price ("Haircut @ ₹99").
9. DO NOT fabricate: if data is not in the context, do not invent it.
10. Anti-repetition: if the conversation history contains a similar message already sent, \
    take a clearly different angle.

COMPULSION LEVERS (use 1–2 per message):
- Specificity       "2,100-patient trial, 38% lower caries recurrence — JIDA Oct 2026 p.14"
- Loss aversion     "6,777 missed searches in your locality last month"
- Social proof      "3 dentists in Lajpat Nagar ran this recall this month"
- Effort extern.    "I've drafted the post — just say go"
- Curiosity         "Want to see who asked?"
- Reciprocity       "Noticed this in your data, thought you'd want to know"
- Asking merchant   "What's your most-asked service this week?"
- Binary commit     "Reply YES to activate / STOP to skip"\
"""


# ---------------------------------------------------------------------------
# Trigger-kind guidance fragments
# ---------------------------------------------------------------------------

def _trigger_guidance(kind: str, payload: dict, top_item: Optional[dict]) -> str:
    p = payload

    guidance_map: dict[str, str] = {
        "research_digest": (
            f"Lead with the digest landing. Cite the specific finding: trial size, "
            f"percentage, source name+page. Tie to the merchant's patient/customer cohort. "
            f"Offer to pull the abstract or draft a patient-ed WhatsApp they can share.\n"
            + (
                f"Top item: \"{top_item['title']}\" — {top_item.get('source','')} — "
                f"trial_n={top_item.get('trial_n','')} — "
                f"patient_segment={top_item.get('patient_segment','')}"
                if top_item else ""
            )
        ),
        "regulation_change": (
            f"Lead with the deadline ({p.get('deadline_iso','soon')}). "
            f"State exactly what changes. Frame as a peer heads-up, not alarm. "
            f"Suggest the specific audit action needed."
            + (f"\nDigest item: {top_item}" if top_item else "")
        ),
        "recall_due": (
            f"Customer-facing recall message (send_as = merchant_on_behalf). "
            f"Name the service due. Offer the specific slots from the payload: "
            f"{p.get('available_slots',[])}. Use the merchant's catalog price. "
            f"Customer's preferred time slot if available. Binary slot-choice CTA."
        ),
        "perf_dip": (
            f"Name the exact metric that dipped: {p.get('metric','?')} "
            f"dropped {abs(p.get('delta_pct', 0))*100:.0f}% vs {p.get('window','?')} baseline "
            f"(baseline={p.get('vs_baseline','?')}). "
            f"Frame with loss aversion. Offer ONE concrete reversible action."
        ),
        "perf_spike": (
            f"Celebrate the specific number: {p.get('metric','?')} up "
            f"{p.get('delta_pct',0)*100:.0f}% in {p.get('window','?')}. "
            f"Link to likely driver: {p.get('likely_driver','')}. "
            f"Suggest capitalising — draft a post, run an offer, or convert interest."
        ),
        "milestone_reached": (
            f"The milestone: {p.get('metric','?')} reaching {p.get('milestone_value','?')} "
            f"(current: {p.get('value_now','?')}). "
            f"{'Imminent — frame as almost-there for one last push.' if p.get('is_imminent') else 'Already hit — celebrate and suggest next milestone.'} "
            f"Social proof lever works well here."
        ),
        "renewal_due": (
            f"Days remaining: {p.get('days_remaining','?')}. Plan: {p.get('plan','')} @ ₹{p.get('renewal_amount','')}. "
            f"Frame around VALUE already created (views, calls, leads in the period) — "
            f"not around 'your subscription expires'. Binary CTA: YES to renew / STOP to discuss."
        ),
        "festival_upcoming": (
            f"Festival: {p.get('festival','')} in {p.get('days_until','?')} days "
            f"({p.get('date','')}). Specific offer tied to the season, advance-booking hook. "
            f"Not generic 'celebrate' — service+price framing. Early-bird or limited-slot angle."
        ),
        "curious_ask_due": (
            f"Ask ONE short, specific question about the merchant's business this week. "
            f"Ask template hint: {p.get('ask_template','')}. "
            f"No preamble, no explanation. Make it trivially easy to reply in one word."
        ),
        "review_theme_emerged": (
            f"Theme: \"{p.get('theme','')}\" appeared {p.get('occurrences_30d',0)}× in last 30 days "
            f"(trend: {p.get('trend','stable')}). "
            f"Quote: \"{p.get('common_quote','')}\". "
            f"Offer to help address it — draft a response template or a process tweak."
        ),
        "winback_eligible": (
            f"Expired {p.get('days_since_expiry',0)} days ago. "
            f"Lapsed customers added since expiry: {p.get('lapsed_customers_added_since_expiry',0)}. "
            f"Perf dip post-expiry: {abs(p.get('perf_dip_pct',0))*100:.0f}%. "
            f"Loss aversion frame: every day without profile = missed searches. "
            f"Binary CTA: YES to reactivate / STOP to skip."
        ),
        "competitor_opened": (
            f"Competitor: \"{p.get('competitor_name','')}\" opened {p.get('distance_km',0):.1f}km away "
            f"on {p.get('opened_date','')}. Their offer: \"{p.get('their_offer','')}\". "
            f"Frame as market intelligence, not alarm. "
            f"Suggest one specific defensive action (a counter-offer, a GBP post, a review campaign)."
        ),
        "dormant_with_vera": (
            f"Merchant has been silent for {p.get('days_since_last_merchant_message',0)} days. "
            f"Last topic: {p.get('last_topic','')}. "
            f"Re-engage with genuine curiosity — ask about something real in their business. "
            f"Do NOT re-introduce yourself. One short question."
        ),
        "active_planning_intent": (
            f"Merchant last said: \"{p.get('merchant_last_message','')}\" — "
            f"topic: {p.get('intent_topic','')}. "
            f"This is ACTION mode. Do not re-qualify. Give the concrete next step directly. "
            f"Use effort-externalization lever: 'I've drafted X — confirm to proceed.'"
        ),
        "supply_alert": (
            f"Alert: molecule={p.get('molecule','')} — batches {p.get('affected_batches',[])} "
            f"from {p.get('manufacturer','')} under voluntary recall. "
            f"Urgency-5. Frame as immediate action item: what to pull, who to notify. "
            f"Offer to filter customer list or draft the recall notice."
        ),
        "chronic_refill_due": (
            f"Molecules due: {p.get('molecule_list',[])}. "
            f"Last refill: {p.get('last_refill','')}. "
            f"Stock runs out: {p.get('stock_runs_out_iso','')}. "
            f"send_as = merchant_on_behalf (message from pharmacy to patient). "
            f"Delivery address saved: {p.get('delivery_address_saved',False)}. "
            f"Time-sensitive: stock runs out soon. Single CTA: order now / call."
        ),
        "category_seasonal": (
            f"Seasonal shifts: {p.get('trends',[])}. "
            f"Recommend specific shelf/stock actions for each trend. "
            f"Data-first: cite the % changes. Offer to draft a GBP post highlighting relevant seasonal items."
        ),
        "gbp_unverified": (
            f"Profile is unverified. Verification path: {p.get('verification_path','')}. "
            f"Estimated uplift on verification: +{p.get('estimated_uplift_pct',0)*100:.0f}% views. "
            f"Frame as missed opportunity. Walk them through the simplest path."
        ),
        "ipl_match_today": (
            f"Match today: {p.get('match','')} at {p.get('venue','')} — "
            f"starts {p.get('match_time_iso','')}. "
            f"Real-time hook for food/restaurant. Specific watch-party offer or match-night combo. "
            f"Time-sensitive — message must go before the match starts."
        ),
        "wedding_package_followup": (
            f"Wedding date: {p.get('wedding_date','')} — "
            f"in {p.get('days_to_wedding',0)} days. "
            f"Trial completed: {p.get('trial_completed','')}. "
            f"Next window: {p.get('next_step_window_open','')}. "
            f"Customer-facing (send_as = merchant_on_behalf). "
            f"Name the specific next step — don't leave it vague."
        ),
        "customer_lapsed_hard": (
            f"Customer lapsed {p.get('days_since_last_visit',0)} days ago. "
            f"Previous focus: {p.get('previous_focus','')}. "
            f"Previous membership: {p.get('previous_membership_months',0)} months. "
            f"send_as = merchant_on_behalf. "
            f"Warm win-back tone — acknowledge the gap, specific re-entry offer."
        ),
        "trial_followup": (
            f"Trial date: {p.get('trial_date','')}. "
            f"Next session options: {p.get('next_session_options',[])}. "
            f"send_as = merchant_on_behalf. "
            f"Capitalise on trial enthusiasm. Specific next date + easy booking CTA."
        ),
        "seasonal_perf_dip": (
            f"Metric {p.get('metric','')} dipped {abs(p.get('delta_pct',0))*100:.0f}% in {p.get('window','')}. "
            + (f"This is an EXPECTED seasonal dip ({p.get('season_note','')}) — acknowledge it, don't alarm. "
               if p.get('is_expected_seasonal') else "")
            + f"Suggest one action to soften the dip."
        ),
        "cde_opportunity": (
            f"CDE webinar/event: digest item {p.get('digest_item_id','')}. "
            f"Credits: {p.get('credits',0)}. Fee: {p.get('fee','')}. "
            f"Frame as a professional development nudge for the practitioner. "
            f"Keep it short — date, credits, cost, single question."
        ),
        "milestone_imminent": (
            f"About to hit a milestone. Frame as one-last-push curiosity."
        ),
    }

    return guidance_map.get(kind, (
        f"Trigger kind: {kind}. Payload: {json.dumps(p, ensure_ascii=False)}. "
        f"Focus on WHY NOW — use the most specific data point from the payload. "
        f"One clear action or question at the end."
    ))


# ---------------------------------------------------------------------------
# CTA decision
# ---------------------------------------------------------------------------

_BINARY_CTA_KINDS = {
    "renewal_due", "winback_eligible", "recall_due", "perf_dip",
    "review_theme_emerged", "festival_upcoming", "competitor_opened",
    "supply_alert", "chronic_refill_due", "customer_lapsed_hard",
    "gbp_unverified", "trial_followup",
}
_NO_CTA_KINDS = {
    "research_digest", "regulation_change", "category_seasonal", "cde_opportunity",
}


def _cta_hint(kind: str) -> str:
    if kind in _BINARY_CTA_KINDS:
        return "binary_yes_stop"
    if kind in _NO_CTA_KINDS:
        return "open_ended (or none if purely informational)"
    return "open_ended"


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_compose_prompt(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None,
    conversation_history: Optional[list[dict]] = None,
) -> str:
    identity = merchant.get("identity", {})
    owner = identity.get("owner_first_name", "")
    languages = identity.get("languages", ["en"])
    lang_hint = "Hindi-English code-mix" if "hi" in languages else (
        "Tamil-English mix" if "ta" in languages else
        "Kannada-English mix" if "kn" in languages else
        "Telugu-English mix" if "te" in languages else "English"
    )

    perf = merchant.get("performance", {})
    offers = merchant.get("offers", [])
    active_offers = [o["title"] for o in offers if o.get("status") == "active"]
    signals = merchant.get("signals", [])
    customer_agg = merchant.get("customer_aggregate", {})

    peer = category.get("peer_stats", {})
    voice = category.get("voice", {})
    digest = category.get("digest", [])
    offer_catalog = category.get("offer_catalog", [])
    vocab_allowed = voice.get("vocab_allowed", [])

    kind = trigger.get("kind", "")
    payload = trigger.get("payload", {})
    suppression_key = trigger.get("suppression_key", "")

    # Resolve digest item referenced by trigger
    top_item: Optional[dict] = None
    ref_id = payload.get("top_item_id") or payload.get("digest_item_id")
    if ref_id:
        for item in digest:
            if item.get("id") == ref_id:
                top_item = item
                break

    # Merge conversation history sources
    history = conversation_history or merchant.get("conversation_history", [])
    history_text = json.dumps(history[-4:], ensure_ascii=False, indent=None) if history else "none"

    # Build customer section
    customer_section = ""
    if customer:
        cid = customer.get("identity", {})
        rel = customer.get("relationship", {})
        customer_section = f"""
=== CUSTOMER CONTEXT (message sent ON BEHALF of merchant to their customer) ===
Name          : {cid.get('name','')}
Language      : {cid.get('language_pref','english')}
Age band      : {cid.get('age_band','')}
State         : {customer.get('state','')}
First visit   : {rel.get('first_visit','')}
Last visit    : {rel.get('last_visit','')}
Visits total  : {rel.get('visits_total','')}
Services      : {rel.get('services_received',[])}
Lifetime value: ₹{rel.get('lifetime_value','')}
Preferences   : {json.dumps(customer.get('preferences',{}), ensure_ascii=False)}
Consent scope : {customer.get('consent',{}).get('scope',[])}
Trigger payload: {json.dumps(payload, ensure_ascii=False)}

→ send_as = "merchant_on_behalf"
→ Language: {cid.get('language_pref','english')}
"""

    prompt = f"""Compose a WhatsApp message for the following context.

=== TRIGGER ===
Kind            : {kind}
Urgency (1-5)   : {trigger.get('urgency',2)}
Source          : {trigger.get('source','')} / scope={trigger.get('scope','')}
Suppression key : {suppression_key}
Payload         : {json.dumps(payload, ensure_ascii=False)}
{f"Resolved digest item: {json.dumps(top_item, ensure_ascii=False)}" if top_item else ""}

=== CATEGORY: {category.get('slug','')} ===
Voice tone    : {voice.get('tone','')}
Taboo words   : {voice.get('vocab_taboo',[])}
Peer stats    : avg_ctr={peer.get('avg_ctr','')} | avg_reviews={peer.get('avg_review_count','')} | avg_views_30d={peer.get('avg_views_30d','')} | scope={peer.get('scope','')}
Vocab allowed : {vocab_allowed}
Offer catalog : {[o['title'] for o in offer_catalog[:5]]}
Seasonal      : {category.get('seasonal_beats',[])}
Trends        : {category.get('trend_signals', [])[:2]}

=== MERCHANT ===
Name          : {identity.get('name','')}
Owner         : {owner}
City/Locality : {identity.get('city','')}, {identity.get('locality','')}
Verified      : {identity.get('verified',False)}
Language pref : {lang_hint}  (raw: {languages})
Subscription  : {json.dumps(merchant.get('subscription',{}), ensure_ascii=False)}
Performance   : views={perf.get('views','')} | calls={perf.get('calls','')} | directions={perf.get('directions','')} | CTR={perf.get('ctr','')} (peer median={peer.get('avg_ctr','')}) | leads={perf.get('leads','')}
7-day delta   : {perf.get('delta_7d',{})}
Active offers : {active_offers}
Signals       : {signals}
Customer agg  : {json.dumps(customer_agg, ensure_ascii=False)}
Review themes : {json.dumps(merchant.get('review_themes',[]), ensure_ascii=False)}
Conv history  : {history_text}
{customer_section}
=== TRIGGER-KIND GUIDANCE ===
{_trigger_guidance(kind, payload, top_item)}

=== COMPOSITION CHECKLIST ===
• Language: {lang_hint}
• CTA style: {_cta_hint(kind)}
• Merchant name to use: {"Dr. " + owner if category.get('slug') == 'dentists' else owner or identity.get('name','')}
• DO NOT repeat any body already in conv history
• Suppression key to embed: {suppression_key}

Return ONLY the JSON object described in the system prompt.\
"""
    return prompt


# ---------------------------------------------------------------------------
# Reply prompt
# ---------------------------------------------------------------------------

def build_reply_prompt(
    conv_history: list[dict],
    merchant_message: str,
    merchant: dict,
    category: dict,
    intent: str,
    is_auto: bool = False,
    trigger: Optional[dict] = None,
) -> str:
    identity = merchant.get("identity", {})
    languages = identity.get("languages", ["en"])
    lang_hint = "Hindi-English code-mix" if "hi" in languages else "English"
    slug = category.get("slug", "")
    owner = identity.get("owner_first_name", "")
    voice = category.get("voice", {})

    trigger_context = ""
    if trigger:
        trigger_context = (
            f"\nOriginal trigger: kind={trigger.get('kind','')} | "
            f"payload={json.dumps(trigger.get('payload',{}), ensure_ascii=False)}"
        )

    if intent == "action":
        return f"""Merchant has given a clear action intent: "{merchant_message}"
DO NOT re-qualify. Switch to action mode immediately.

Merchant: {identity.get('name','')} ({slug})
Owner: {owner}
Language: {lang_hint}
Voice tone: {voice.get('tone','')}
Conversation: {json.dumps(conv_history[-4:], ensure_ascii=False)}{trigger_context}

Compose the NEXT STEP message — what you (Vera) are now doing for them, \
or what you need to proceed. Use effort-externalization lever ("I've drafted X, confirm to proceed").
IMPORTANT: The body MUST include at least one of these English words: \
"confirm", "proceed", "next", "draft", "sending", "here", "done".

Return JSON: {{"action": "send", "body": "<message>", "cta": "open_ended", \
"rationale": "<why this next step>"}}\
"""

    return f"""Merchant replied: "{merchant_message}" (intent: {intent})

Merchant: {identity.get('name','')} ({slug}), language: {lang_hint}
Voice tone: {voice.get('tone','')}
Conversation: {json.dumps(conv_history[-4:], ensure_ascii=False)}{trigger_context}

Continue the conversation naturally. Advance the goal from the previous message. \
Keep the same voice and language. Use a specific fact from the trigger or conversation if available.

Return JSON: {{"action": "send", "body": "<message>", "cta": "open_ended", \
"rationale": "<why this reply>"}}\
"""
