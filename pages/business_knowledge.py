"""Business Knowledge page."""

import os
import re
import random
import hashlib
import streamlit as st
from shared import get_theme


FAQ_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "faq_files")


@st.cache_data(ttl=600)
def _load_faq_entries():
    entries = []
    if not os.path.isdir(FAQ_DIR):
        return entries
    for fname in sorted(os.listdir(FAQ_DIR)):
        if not fname.endswith(".md"):
            continue
        product = fname.replace(".md", "").lower()
        with open(os.path.join(FAQ_DIR, fname), encoding="utf-8") as f:
            raw = f.read()
        for block in re.split(r"={3,}END={3,}", raw):
            block = block.strip()
            if not block:
                continue
            title_m = re.search(r"TITLE:\s*(.+?)(?:\n|PRODUCT:)", block)
            content_m = re.search(r"CONTENT:\s*(.+?)(?=\nTAGS:|\Z)", block, re.DOTALL)
            tags_m = re.search(r'TAGS:\s*\[(.+?)\]', block, re.DOTALL)
            title = title_m.group(1).strip().replace("\\*\\*", "**").replace("\\*", "*") if title_m else ""
            content = content_m.group(1).strip() if content_m else ""
            if not content:
                continue
            # light cleanup of escaped markdown
            for esc in ["\\*\\*", "\\*", "\\-\\--", "\\-\\-\\-", "\\-\\-"]:
                content = content.replace(esc, esc.replace("\\", ""))
                title = title.replace(esc, esc.replace("\\", ""))
            tags_raw = tags_m.group(1) if tags_m else ""
            tags = [t.strip().strip('"').strip("'").strip('""')
                    for t in tags_raw.split(",") if t.strip()]
            entries.append({
                "product": product, "title": title, "content": content, "tags": tags,
                "searchable": f"{title} {content} {' '.join(tags)}".lower(),
            })
    return entries


def _search_faq(query, entries):
    q_words = set(re.findall(r'\w+', query.lower()))
    if not q_words:
        return []
    scored = []
    for e in entries:
        hits = sum(1 for w in q_words if w in e["searchable"])
        if hits == 0:
            continue
        bonus = 3 if query.lower() in e["searchable"] else 0
        title_hits = sum(1 for w in q_words if w in e["title"].lower())
        scored.append((hits + bonus + title_hits * 2, e))
    scored.sort(key=lambda x: -x[0])
    return scored[:3]


_DYK_FACTS = [
    {
        "title": "The 15% Reward Share",
        "body": "Standard 1-Phase and 2-Step traders can earn an extra **15% of the Challenge profit target** "
                "as a one-time reward. The catch? You only unlock it once you hit your **first scale-up** "
                "under the Growth Program.\n\n"
                "**Example:** A $50K Standard 2-Phase has an 8% Phase 1 profit target ($4,000). "
                "After your first scale-up, you'd receive **$600** extra (15% of $4,000). Basic Lite and "
                "Futures accounts don't get this.",
    },
    {
        "title": "The $1,000 Brand Promise",
        "body": "AcmeCorp guarantees every Performance Reward is processed within **24 hours**. "
                "If they miss that window, they add an extra **$1,000** to your payout.\n\n"
                "**Example:** You request a $2,000 withdrawal at 9 AM Monday. If it's not "
                "processed by 9 AM Tuesday, you receive **$3,000** instead.",
    },
    {
        "title": "Breach Rate Is ~94%",
        "body": "About **93.7%** of all accounts end up violated. The top reasons:\n"
                "- **Monthly Loss Limit**: 37.8%\n"
                "- **Daily Loss Limit**: 32.9%\n"
                "- **Profit Target Reached**: 26.5% (this is actually the good one!)\n\n"
                "So roughly 1 in 4 breaches is a trader *passing* the challenge, not failing.",
    },
    {
        "title": "No Time Limits -- Seriously",
        "body": "Every AcmeCorp Evaluation (CFD and Futures) has **zero time limit**. "
                "You can take days, weeks, or months to hit the profit target.\n\n"
                "**Example:** You buy a Standard 2-Phase $25K on January 1st. If you only trade "
                "twice a week and take 3 months, that's perfectly fine. No pressure, no deadline.",
    },
    {
        "title": "The Double Up Add-On",
        "body": "For an extra **40%** at checkout, the Double Up add-on gets you a second "
                "Challenge account of the same size -- effectively **60% off** the second account.\n\n"
                "**Example:** A $50K Standard 2-Phase costs $299. With Double Up it's ~$419 total "
                "-- that's two $50K Challenges instead of one. If you pass both, you can hold "
                "up to **$600K** funded (vs the normal $300K cap).",
    },
    {
        "title": "Weekend Holding Trap",
        "body": "During the **Challenge phase**, you can hold positions over the weekend on CFD accounts. "
                "But once you get **funded** (AcmeCorp Account), weekend holding is **not allowed**.\n\n"
                "**Example:** You hold a gold trade on Friday afternoon during your Phase 2 -- totally fine. "
                "You do the same thing after passing -- your position must be closed before the weekend. "
                "Many traders get caught by this rule change.",
    },
    {
        "title": "Passing Reward Is Not Instant",
        "body": "The Challenge fee refund (Passing Reward) is **not paid right after passing**. "
                "It's linked to the **Scale-Up Program** and only becomes available after meeting "
                "specific milestones.\n\n"
                "**Example:** You paid $299.99 for a Standard 2-Phase $50K. After passing, you don't "
                "get $299.99 back immediately. You receive it during the Scale-Up phase, "
                "typically with your 3rd+ Performance Reward.",
    },
    {
        "title": "Gambling = Account Warning",
        "body": "Using **70% or more** of your available margin on a single trade is flagged as "
                "gambling-like behavior. First time = warning. On funded accounts, profits from "
                "those trades get **deducted**. Repeat = account termination.\n\n"
                "**Pro tip:** Professional traders typically use 20-30% margin and risk only "
                "1% of account balance per trade.",
    },
    {
        "title": "Standard 1-Phase Has Tighter Limits",
        "body": "Standard 1-Phase is faster (single phase, 10% target, 2 min trading days) "
                "but has **stricter risk limits** than 2-Step.\n\n"
                "- **1-Step**: 3% daily loss, 6% max loss (balance-based)\n"
                "- **2-Step**: 5% daily loss, 10% max loss (balance-based)\n\n"
                "Both use balance-based drawdown (not trailing). The key difference is 1-Step gives you "
                "half the daily loss room (3% vs 5%) and almost half the max loss (6% vs 10%). "
                "Only Direct Start uses trailing drawdown.",
    },
    {
        "title": "US Traders Have Different Rules",
        "body": "US-based traders can only use **Platform-D or Platform-C** (no Platform-B/Platform-A due to "
                "PlatformProvider restrictions). Switching from Platform-D to Platform-C costs **$25**.\n\n"
                "Also: **Direct Start, Free Trial, and Competition accounts** are "
                "**not available** in the US. EAs are not allowed on Platform-D or Platform-C.",
    },
    {
        "title": "Top Countries by Revenue",
        "body": "Our top markets by order volume and revenue are:\n"
                "1. **Country A**\n2. **Country B**\n3. **Country C**\n4. **Country D**\n\n"
                "Average order value is around **$150**. These four markets "
                "consistently drive the majority of new signups and purchases.",
    },
    {
        "title": "News Trading? Keep Only 40%",
        "body": "On funded CFD accounts, if your Take Profit or Stop Loss triggers within **5 minutes** "
                "of a high-impact news event, **60% of that trade's profit is deducted** -- you keep only 40%. "
                "This applies even if you opened the trade *days ago*. During the Challenge phase, there's no deduction.\n\n"
                "**Example:** You open a trade on Monday. On Friday, NFP drops and your TP hits 3 minutes "
                "after the release. Even though the trade was 5 days old, 60% of that profit is clipped.",
    },
    {
        "title": "Scale-Up to $4 Million",
        "body": "The AcmeCorp Pro Scale-Up program can grow a CFD account up to **$4,000,000** at "
                "**25% per stage**, but each stage requires at least **2 months** and **4 reward cycles** "
                "with a minimum 4% growth each.\n\n"
                "**Example:** A $100K account scales to $125K after 2 months. Reaching $4M would require "
                "~16 successful scale-up stages -- at least 32 months of consistent trading.",
    },
    {
        "title": "Phase 2 Reset = Back to Phase 1",
        "body": "If you breach during **Phase 2** of a 2-Step challenge and choose to reset, "
                "you go back to **Phase 1** -- not Phase 2. You cannot skip ahead. "
                "The full reset fee applies.\n\n"
                "**Example:** You passed Phase 1 and are halfway through Phase 2, but hit the MLL. "
                "After paying the reset fee, you start over from Phase 1 again.",
    },
    {
        "title": "Crypto Leverage Is Always 1:1",
        "body": "Across **ALL** CFD account types -- Challenge, Funded, 1-Step, 2-Step, Lite, Instant "
                "-- crypto leverage is capped at **1:1**. You need the full notional value to open a "
                "crypto position. No margin benefit whatsoever.\n\n"
                "**Example:** To open $10,000 worth of BTC on a $100K account, you need $10,000 in margin "
                "-- 10% of your account for a single position.",
    },
    {
        "title": "$50K Cap for 8 Countries",
        "body": "Traders from certain restricted regions have a **$50K maximum** across all active funded accounts "
                "(or $100K with Double Up).\n\n"
                "**Example:** A trader in a capped region with a $50K funded account passes another $50K challenge. "
                "The second account is placed **on hold indefinitely** -- they can't use it until the first one is closed.",
    },
    {
        "title": "First 2-Step Payout? Wait 21 Days",
        "body": "Standard 2-Phase and Basic Lite funded accounts require **21 calendar days** of trading "
                "before the first reward becomes available. After that, payouts are bi-weekly. "
                "Only Standard 1-Phase offers rewards every **5 business days** from day one.\n\n"
                "**Example:** You pass the 2-Step and start funded trading on Jan 3. Your first "
                "payout request can't happen until Jan 24, regardless of how much profit you've made.",
    },
    {
        "title": "EAs Without Add-On = Termination",
        "body": "Using Expert Advisors (bots/EAs) without purchasing the **EA Add-On** is a rule violation "
                "that can lead to **account termination**. The add-on costs **$5-$30** depending on account size. "
                "VPS can only be purchased as a bundle with the EA add-on ($10-$60).\n\n"
                "**Example:** A trader deploys an EA on their $100K account without the $30 add-on. "
                "The account gets flagged and terminated -- over a $30 add-on.",
    },
    {
        "title": "Up to 500% Passing Reward",
        "body": "AcmeCorp runs periodic campaigns where the Passing Reward (challenge fee refund) "
                "can be multiplied to **120%, 150%, 300%, or even 500%** of the original fee. "
                "This is on top of regular performance rewards.\n\n"
                "**Example:** You paid $499 for a challenge during a 300% campaign. After passing "
                "and reaching the right reward cycle, you receive **$1,497** back (3x $499).",
    },
    {
        "title": "Basic Lite Has a Lower $200K Cap",
        "body": "While standard CFD funded accounts can hold up to **$300K** (or $600K with Double Up), "
                "Basic Lite accounts have a separate, lower cap of **$200,000** total across all active "
                "Lite accounts.\n\n"
                "**Example:** A trader with two $100K Basic Lite funded accounts is at the $200K Lite cap. "
                "To grow further, they'd need a different account type (1-Step or 2-Step).",
    },
    {
        "title": "Reset = Smaller Fee Refund",
        "body": "When you fail and reset a challenge, you pay a **discounted reset fee** (lower than the original). "
                "But here's the catch: your Passing Reward (fee refund) is based on **what you last paid** "
                "(the reset fee), not your original purchase price.\n\n"
                "**Example:** You bought a $100K 2-Step for **$499**. You fail and reset for **$449** (10% off). "
                "You pass this time. Your Passing Reward refund = **$449**, not $499. "
                "You effectively lost **$50** because the refund is tied to the cheaper reset fee.",
    },
    {
        "title": "Add-Ons: Buy Now or Never",
        "body": "All CFD add-ons (Swap-Free, 95% Lifetime Reward, Double Up, No Minimum Trading Days, "
                "Bi-Weekly Reward, EA Add-On) can **only be selected during the initial purchase** at "
                "checkout. You cannot add them later, even if you're willing to pay.\n\n"
                "**Example:** You buy a $100K 2-Step without the 95% Lifetime Reward add-on. After passing "
                "Phase 1 you realize you want it. Too late -- the only option is to buy a new challenge.",
    },
    {
        "title": "Swap-Free Costs 10% More",
        "body": "Swap-free accounts (no overnight holding charges) are priced **10% higher** than regular "
                "accounts. This is a permanent price premium applied at purchase, not a recurring fee.\n\n"
                "**Example:** A $100K Standard 2-Phase at $499 becomes **~$549** with the Swap-Free add-on. "
                "Useful for traders who hold positions for multiple days and want to avoid swap charges.",
    },
    {
        "title": "30 Days Inactive = Account Gone",
        "body": "AcmeCorp enforces a **30-day inactivity rule** on ALL CFD account types -- Challenge, "
                "Funded, and Instant. If you place **zero trades for 30 consecutive days**, the system "
                "deactivates your account automatically. You cannot extend this period.\n\n"
                "**Example:** You pass your Challenge, get your AcmeCorp Account on Jan 1, go on vacation, "
                "and don't trade until Feb 1 -- your account is gone. Place at least one trade every few weeks.",
    },
    {
        "title": "Miss KYC by 30 Days? Challenge Wasted",
        "body": "After passing a Challenge, you have exactly **30 days** to complete KYC verification. "
                "Miss this deadline and your Challenge account is **deactivated and void** -- even if you "
                "traded perfectly. Completing KYC late does NOT retroactively qualify you.\n\n"
                "**Example:** You pass Phase 2 on March 1 but procrastinate on KYC until April 5 "
                "-- your entire Challenge is void. You'd have to buy a brand-new one.",
    },
    {
        "title": "Direct Start Has NO Daily Loss Limit",
        "body": "Unlike every other CFD account type, Direct Start has **no Daily Loss Limit** at all. "
                "It relies entirely on a **6% Trailing MLL** that follows your highest equity upward "
                "but never moves back down.\n\n"
                "**Example:** On a $10K Instant account, if your balance grows to $11K, the MLL moves up "
                "to $10,340 (6% below $11K). If equity then drops to $10,340, you're violated -- regardless "
                "of whether the loss happened in one day or over several weeks.",
    },
    {
        "title": "Instant Withdrawal Trap",
        "body": "In Direct Start, the trailing MLL is **capped** -- it can never rise above your "
                "original starting balance. This means withdrawing all your profit can leave you at "
                "exactly the MLL level, causing an **instant breach**.\n\n"
                "**Example:** You start at $10K, grow to $10,700, the MLL locks at $10,000. "
                "You withdraw $700 -- balance returns to $10,000 = MLL level = **violated immediately**. "
                "Always keep a buffer above the MLL when withdrawing.",
    },
    {
        "title": "Only 2 Devices Allowed",
        "body": "AcmeCorp limits you to **2 personal devices** for accessing your trading account. "
                "Your first logged-in device becomes the default. **Device sharing** -- using someone else's "
                "phone, laptop, or tablet -- is strictly prohibited and can trigger account termination.\n\n"
                "**Example:** Trading from your laptop and phone is fine. Logging in from your "
                "friend's computer is a violation that could get your account flagged.",
    },
    {
        "title": "Merging Accounts? Lowest Reward Wins",
        "body": "AcmeCorp lets you merge multiple funded accounts into one (up to $300K), but the "
                "merged account adopts the **LOWEST reward percentage** among all accounts. All accounts "
                "must be the same Challenge type, have no open trades, and no negative balance.\n\n"
                "**Example:** You merge a **95% reward** account with an **80% reward** account. "
                "The merged result is **80%** -- the lower one wins. Direct Start accounts cannot be merged.",
    },
    {
        "title": "Direct Start: 70% Reward at Start",
        "body": "While all Challenge-based accounts (1-Step, 2-Step, Lite) start at **80%** reward share, "
                "Direct Start starts at only **70%** for Tiers 1 and 2. You reach 80% at Tier 3 -- "
                "and 80% is the **maximum** for Instant (no 95% Lifetime Add-On available).\n\n"
                "**Example:** On a $10K Instant at Tier 1, $1,000 profit nets you **$700** (70%). "
                "The same profit on a 2-Step funded account gives you **$800** (80%), or $950 with the 95% add-on.",
    },
    {
        "title": "Direct Start Grows by Tiers, Not Scale-Up",
        "body": "Unlike 1-Step/2-Step that use the Growth Program (25% per stage), Direct Start "
                "uses a **tier-based system**. To move up a tier, you must actually **withdraw 10%** of your "
                "starting balance. Each tier adds your original balance to the account.\n\n"
                "**Example:** Start at $10K. Withdraw $1K to reach Tier 2 ($20K), withdraw $2K for "
                "Tier 3 ($30K), and so on up to **$200K** (10x your start) or even $2M with approval.",
    },
    {
        "title": "Basic Lite: No 15% Challenge Reward",
        "body": "The 15% Reward Share from challenge phase profits is available **only for Standard 1-Phase "
                "and 2-Step**. Basic Lite traders receive **zero** profit share from the challenge phase, "
                "even though they pay a fee and go through the same phases.\n\n"
                "**Example:** Two traders pass with $5K profit. The 2-Step trader gets **$750** as a "
                "challenge reward after first scale-up; the Lite trader gets **nothing** from that profit.",
    },
    {
        "title": "$25 Fee for Platform-C or Platform-D",
        "body": "Global (non-US) clients who choose **Platform-C or Platform-D** at checkout must pay a "
                "one-time **$25 platform fee** on top of the Challenge price. US clients are exempt. "
                "Once any trade is placed, **platform switching is permanently locked**.\n\n"
                "**Example:** A $50K 2-Step costs $299. If you pick Platform-C, total is **$324**. "
                "If you later want to switch to Platform-A, it's too late once you've placed your first trade.",
    },
    {
        "title": "Minimum Payout Is $20",
        "body": "AcmeCorp won't process a reward withdrawal below **$20**. If your profit for a cycle "
                "is under $20, it automatically **carries forward** to the next cycle. For PayProvider and "
                "USDC, the minimum is **$50**.\n\n"
                "**Example:** You earn $15 in Cycle 1 and $30 in Cycle 2. You can only withdraw the "
                "combined $45 after Cycle 2, since $15 alone was below the $20 threshold.",
    },
    {
        "title": "No Company Accounts -- Individuals Only",
        "body": "AcmeCorp requires all traders to register as **individuals** using their personal "
                "legal name. Business or company registrations are **not permitted**. Your name must match "
                "your KYC document (passport, national ID, or driving license) exactly.\n\n"
                "**Example:** Registering as 'ABC Trading LLC' will be rejected. You must use your "
                "personal name exactly as it appears on your government-issued ID.",
    },
    {
        "title": "Free Trial: 14 Days, No Crypto, Manual Only",
        "body": "AcmeCorp offers a **free trial** to test the platform, but with strict limits: "
                "**14 calendar days**, at least **3 trading days**, a **5% profit target**, and "
                "**manual trading only** (no EAs, no bots). Crypto is not available on trial.\n\n"
                "**Example:** You're limited to one trial per email/IP. Passing the trial does NOT "
                "guarantee a funded account -- it's purely for practice.",
    },
    {
        "title": "Some Countries Are Surprisingly Restricted",
        "body": "Beyond the usual sanctioned nations, AcmeCorp's CFD restricted list "
                "includes some unexpected entries across Asia, Europe, and the Caribbean.\n\n"
                "Some restricted regions have operational connections to the company. "
                "Using a **VPN from a restricted country** is grounds for immediate termination.",
    },
    {
        "title": "1-Step: Only 2 Trading Days to Pass",
        "body": "While Standard 2-Phase and Lite require **5 minimum trading days** per phase, "
                "Standard 1-Phase requires only **2 trading days**. You could hit the 10% profit target "
                "in just two sessions and pass.\n\n"
                "**Example:** You open a $50K 1-Step on Monday, trade Monday and Tuesday, "
                "hit 10% profit -- you've met all requirements and can pass. No need to wait 5 days.",
    },
]


def render():
    _T = get_theme()

    st.header("Business Knowledge")
    st.caption("Learn about AcmeCorp -- search any topic or pick up something new below.")

    all_entries = _load_faq_entries()

    # ── Search box ────────────────────────────────────────────
    search_query = st.text_input(
        "What do you want to know?",
        placeholder="e.g. '15% profit share', 'reset discount', 'leverage', 'weekend holding'...",
        key="bk_search",
    )

    if search_query.strip():
        results = _search_faq(search_query, all_entries)
        if results:
            # Show the best match as a direct answer
            best = results[0][1]
            badge = "CFD" if best["product"] == "cfd" else "Futures"
            st.markdown(f"#### {best['title']}")
            st.caption(badge)
            st.markdown(best["content"])

            # Show related topics if there are more
            if len(results) > 1:
                st.markdown("---")
                st.markdown("**Related topics**")
                for _, entry in results[1:]:
                    b = "CFD" if entry["product"] == "cfd" else "Futures"
                    with st.expander(f"{b} -- {entry['title']}"):
                        st.markdown(entry["content"])
        else:
            st.warning("Couldn't find a match. Try keywords like **payout**, **breach**, **challenge**, **leverage**, **reset**.")

    # ── Did You Know? ─────────────────────────────────────────
    st.markdown("")
    st.markdown("---")

    # Pick a different fact each time the page renders
    if "dyk_seed" not in st.session_state:
        st.session_state.dyk_seed = random.randint(0, 999999)

    _col_shuffle, _ = st.columns([1, 3])
    with _col_shuffle:
        if st.button("\U0001f500 Show me more", key="dyk_shuffle", use_container_width=True):
            st.session_state.dyk_seed = random.randint(0, 999999)
            st.rerun()

    _rng = random.Random(st.session_state.dyk_seed)
    _picked = _rng.sample(_DYK_FACTS, min(2, len(_DYK_FACTS)))

    _colors = ["#4361ee", "#2a9d8f"]
    for _fact, _clr in zip(_picked, _colors):
        st.markdown(
            f"""<div style="background: {_T['card_bg']};
            border-radius: 12px; padding: 24px 28px; border-left: 4px solid {_clr};
            margin-bottom: 16px;">
            <div style="color: {_T['card_label']}; font-size: 12px; text-transform: uppercase;
            letter-spacing: 1.5px; margin-bottom: 8px;">Did you know?</div>
            <div style="color: {_T['card_title']}; font-size: 18px; font-weight: 600;
            margin-bottom: 12px;">{_fact['title']}</div>
            <div style="color: {_T['card_body']}; font-size: 14px; line-height: 1.6;">
            {_fact['body'].replace(chr(10), '<br>')}</div>
            </div>""",
            unsafe_allow_html=True,
        )
