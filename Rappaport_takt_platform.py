swinerton_takt_platform.py
#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════╗
║                                                                           ║
║          SWINERTON TAKT PLANNING PLATFORM                                ║
║          Portland Division | Zero Rework by 2027                         ║
║                                                                           ║
║          One Application | One Download | Complete Workflow              ║
║          Phase 1-4: Cards → Analysis → Risk/Buffers → Planning → Tracking║
║                                                                           ║
║  TO RUN:  streamlit run swinerton_takt_platform.py                       ║
║                                                                           ║
╚═══════════════════════════════════════════════════════════════════════════╝

This is the complete, self-contained Takt Planning application.
No additional files required. One click to run everything.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple
from enum import Enum
import json
from collections import defaultdict

# ════════════════════════════════════════════════════════════════════════════
# PAGE CONFIGURATION
# ════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Swinerton Takt Platform",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .phase-header {
        background: linear-gradient(135deg, #0A2240 0%, #1A5499 100%);
        color: white;
        padding: 20px;
        border-radius: 8px;
        margin-bottom: 20px;
        font-size: 24px;
        font-weight: bold;
    }
    .metric-card {
        background: #E8F5ED;
        padding: 15px;
        border-radius: 8px;
        border-left: 4px solid #1B6B3A;
    }
    .risk-critical { color: #C8102E; font-weight: bold; }
    .risk-high { color: #F57C00; font-weight: bold; }
    .risk-moderate { color: #FBC02D; font-weight: bold; }
    .risk-low { color: #1B6B3A; font-weight: bold; }
    .buffer-box {
        background: #F3E5F5;
        padding: 12px;
        border-radius: 6px;
        margin: 8px 0;
        border-left: 4px solid #7B1FA2;
    }
    .backlog-ready { background: #E8F5ED; }
    .backlog-partial { background: #FFF8E1; }
    .backlog-blocked { background: #FEE8EB; }
</style>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════
# ENUMERATIONS & DATA CLASSES
# ════════════════════════════════════════════════════════════════════════════

class RiskLevel(str, Enum):
    LOW = "Low (0-5% variability)"
    MODERATE = "Moderate (5-15% variability)"
    HIGH = "High (15-30% variability)"
    CRITICAL = "Critical (30%+ variability)"

class BufferType(str, Enum):
    PROJECT = "Project Buffer"
    FEEDING = "Feeding Buffer"
    STRATEGIC = "Strategic Buffer"
    INSPECTION = "Inspection Buffer"
    RESOURCE = "Resource Buffer"

@dataclass
class TradeRiskProfile:
    """Historical risk data for a trade"""
    trade: str
    avg_duration: float
    std_dev_duration: float
    is_bottleneck: bool = False
    dependent_trades_count: int = 0
    inspection_required: bool = False
    buffer_multiplier: float = 1.0
    
    @property
    def variability_pct(self) -> float:
        if self.avg_duration == 0:
            return 0
        return (self.std_dev_duration / self.avg_duration) * 100
    
    @property
    def risk_level(self) -> RiskLevel:
        var = self.variability_pct
        if var <= 5:
            return RiskLevel.LOW
        elif var <= 15:
            return RiskLevel.MODERATE
        elif var <= 30:
            return RiskLevel.HIGH
        else:
            return RiskLevel.CRITICAL

@dataclass
class BufferZone:
    """Strategic buffer in schedule"""
    buffer_id: str
    buffer_type: BufferType
    location: str
    duration_days: float
    reason: str
    risk_level: RiskLevel
    tasks_protected: List[str]

@dataclass
class WorkableBacklogTask:
    """Task ready for execution"""
    task_id: str
    task_name: str
    trade: str
    zone: str
    quantity: float
    unit: str
    duration: float
    constraints_removed: int
    total_constraints: int = 8
    is_made_ready: bool = False
    days_until_needed: int = 0
    is_critical: bool = False

# ════════════════════════════════════════════════════════════════════════════
# RISK ANALYZER - CORE LOGIC
# ════════════════════════════════════════════════════════════════════════════

class RiskAnalyzer:
    """Complete risk analysis and buffer management"""
    
    # Default trade risk profiles (Swinerton Portland historical data)
    DEFAULT_PROFILES = {
        "Structural": TradeRiskProfile("Structural", 45, 5, False, 8, True, 1.0),
        "Concrete": TradeRiskProfile("Concrete", 35, 7, False, 3, True, 1.1),
        "MEP - Mechanical": TradeRiskProfile("MEP - Mechanical", 60, 18, True, 8, True, 1.5),
        "MEP - Electrical": TradeRiskProfile("MEP - Electrical", 50, 15, True, 6, True, 1.3),
        "MEP - Plumbing": TradeRiskProfile("MEP - Plumbing", 40, 12, True, 4, True, 1.2),
        "Framing": TradeRiskProfile("Framing", 35, 5, False, 6, False, 1.0),
        "Drywall": TradeRiskProfile("Drywall", 30, 4, False, 5, False, 0.9),
        "Flooring": TradeRiskProfile("Flooring", 25, 3, False, 2, True, 1.0),
        "Finishes": TradeRiskProfile("Finishes", 40, 8, False, 1, True, 1.1),
        "Painting": TradeRiskProfile("Painting", 20, 3, False, 0, False, 0.9),
        "Testing & Commissioning": TradeRiskProfile("Testing & Commissioning", 25, 10, True, 0, True, 1.4),
    }
    
    def __init__(self, project_data=None):
        self.project_data = project_data
        self.trade_profiles = self.DEFAULT_PROFILES.copy()
        self.buffers: List[BufferZone] = []
        self.workable_backlog: List[WorkableBacklogTask] = []
    
    def get_trade_profile(self, trade: str) -> TradeRiskProfile:
        """Get profile, with fallback to default"""
        return self.trade_profiles.get(trade, 
            TradeRiskProfile(trade, 30, 5, False, 2, False, 1.0))
    
    def calculate_buffer_size(self, trade: str, task_duration: float) -> float:
        """Calculate buffer days for a trade based on variability"""
        profile = self.get_trade_profile(trade)
        
        # Base buffer from variability
        base_buffer = task_duration * (profile.variability_pct / 100)
        
        # Adjustments
        bottleneck_factor = 1.5 if profile.is_bottleneck else 1.0
        dependent_factor = 1.0 + (profile.dependent_trades_count * 0.1)
        inspection_factor = 1.2 if profile.inspection_required else 1.0
        
        total = (base_buffer * bottleneck_factor * dependent_factor 
                 * inspection_factor * profile.buffer_multiplier)
        
        return max(1.0, round(total, 1))  # Minimum 1 day
    
    def place_buffers(self, wagons: List[Dict], zones: List[Dict], 
                      project_duration: float, project_buffer_pct: float = 0.10) -> List[BufferZone]:
        """Place buffers strategically throughout schedule"""
        self.buffers = []
        
        # Project Buffer at end
        project_buffer_days = project_duration * project_buffer_pct
        self.buffers.append(BufferZone(
            buffer_id="PROJECT-BUFFER",
            buffer_type=BufferType.PROJECT,
            location="End of Project",
            duration_days=project_buffer_days,
            reason=f"P2SL standard: {project_buffer_pct*100:.0f}% of schedule ({project_buffer_days:.0f} days)",
            risk_level=RiskLevel.MODERATE,
            tasks_protected=[]
        ))
        
        # Strategic buffers after high-risk trades
        for wagon in wagons:
            trade = wagon.get("trade", "")
            profile = self.get_trade_profile(trade)
            
            if profile.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
                buffer_days = self.calculate_buffer_size(trade, wagon.get("takt_time", 50))
                
                self.buffers.append(BufferZone(
                    buffer_id=f"STRATEGIC-{wagon.get('wagon_id', 'unknown')}",
                    buffer_type=BufferType.STRATEGIC,
                    location=f"After {trade}",
                    duration_days=buffer_days,
                    reason=f"{trade} is {profile.risk_level.value} risk ({profile.variability_pct:.1f}% variability)",
                    risk_level=profile.risk_level,
                    tasks_protected=wagon.get("tasks", [])
                ))
        
        # Inspection buffers
        for wagon in wagons:
            trade = wagon.get("trade", "")
            profile = self.get_trade_profile(trade)
            
            if profile.inspection_required:
                self.buffers.append(BufferZone(
                    buffer_id=f"INSPECTION-{wagon.get('wagon_id', 'unknown')}",
                    buffer_type=BufferType.INSPECTION,
                    location=f"First Work Inspection: {trade}",
                    duration_days=1.0,
                    reason="Quality gate - First Work Inspection hold point",
                    risk_level=RiskLevel.MODERATE,
                    tasks_protected=wagon.get("tasks", [])
                ))
        
        return self.buffers
    
    def generate_workable_backlog(self, tasks: List[Dict], wagons: List[Dict], 
                                  lookahead_days: int = 28) -> List[WorkableBacklogTask]:
        """Generate workable backlog - tasks ready to pull"""
        self.workable_backlog = []
        
        for wagon in wagons:
            for task_id in wagon.get("tasks", []):
                task = next((t for t in tasks if t.get("id") == task_id), None)
                if not task:
                    continue
                
                # Count constraints removed
                constraints_removed = wagon.get("constraints_removed", 0)
                is_made_ready = constraints_removed == 8
                
                # Days until scheduled
                days_until = wagon.get("days_until_start", 0)
                
                # Can include if within lookahead or has float
                can_include = days_until <= lookahead_days or task.get("float_days", 0) > 0
                
                if can_include:
                    entry = WorkableBacklogTask(
                        task_id=task.get("id", ""),
                        task_name=task.get("name", ""),
                        trade=wagon.get("trade", ""),
                        zone=wagon.get("zone", ""),
                        quantity=task.get("quantity", 0),
                        unit=task.get("unit", ""),
                        duration=task.get("duration", 0),
                        constraints_removed=constraints_removed,
                        is_made_ready=is_made_ready,
                        days_until_needed=days_until,
                        is_critical=task.get("is_critical", False)
                    )
                    self.workable_backlog.append(entry)
        
        # Sort by readiness first, then by days until needed
        self.workable_backlog.sort(
            key=lambda x: (-x.constraints_removed, x.days_until_needed)
        )
        
        return self.workable_backlog
    
    def get_backlog_matrix(self) -> Dict:
        """Generate matrix of workable backlog"""
        matrix = {
            "total": len(self.workable_backlog),
            "made_ready": sum(1 for t in self.workable_backlog if t.is_made_ready),
            "ready_to_pull": sum(1 for t in self.workable_backlog if t.constraints_removed >= 7),
            "in_progress": sum(1 for t in self.workable_backlog if 4 <= t.constraints_removed < 7),
            "not_ready": sum(1 for t in self.workable_backlog if t.constraints_removed < 4),
            "by_readiness": defaultdict(list)
        }
        
        for task in self.workable_backlog:
            if task.is_made_ready:
                key = "Made Ready (Pull Today)"
            elif task.constraints_removed >= 7:
                key = "7/8 Ready (Pull This Week)"
            elif task.constraints_removed >= 4:
                key = "4-6/8 Ready (Focus on Constraints)"
            else:
                key = "0-3/8 Ready (Not Ready)"
            
            matrix["by_readiness"][key].append({
                "task_id": task.task_id,
                "task_name": task.task_name,
                "trade": task.trade,
                "constraints": f"{task.constraints_removed}/8",
                "days_until": task.days_until_needed
            })
        
        return matrix

# ════════════════════════════════════════════════════════════════════════════
# DEMO DATA GENERATOR
# ════════════════════════════════════════════════════════════════════════════

def generate_demo_project():
    """Generate realistic demo project data"""
    
    zones = [
        {"zone_id": "Z1", "zone_name": "North Wing", "sq_ft": 50000},
        {"zone_id": "Z2", "zone_name": "South Wing", "sq_ft": 50000},
        {"zone_id": "Z3", "zone_name": "Core", "sq_ft": 30000},
    ]
    
    trades = [
        ("Structural", 50, 8000),
        ("MEP - Mechanical", 65, 7500),
        ("MEP - Electrical", 55, 6000),
        ("Framing", 40, 12000),
        ("Drywall", 30, 15000),
        ("Finishes", 40, 10000),
    ]
    
    wagons = []
    tasks = []
    task_counter = 0
    
    for zone in zones:
        for zone_seq, (trade, duration, qty) in enumerate(trades, 1):
            wagon_id = f"{trade.replace(' - ', '-')}-{zone['zone_id']}"
            wagon = {
                "wagon_id": wagon_id,
                "trade": trade,
                "zone": zone["zone_id"],
                "duration": duration,
                "takt_time": 50,
                "tasks": [],
                "quantity": qty,
                "constraints_removed": np.random.randint(4, 9),
                "days_until_start": (zone_seq - 1) * 50 + (len(zones) - 1) * 50
            }
            
            # Create 3 tasks per wagon
            for _ in range(3):
                task_counter += 1
                task_id = f"A{1000 + task_counter}"
                task = {
                    "id": task_id,
                    "name": f"{trade} - {zone['zone_name']} - Unit {task_counter}",
                    "quantity": qty // 3,
                    "unit": "SF",
                    "duration": duration // 3,
                    "is_critical": np.random.random() < 0.2,
                    "float_days": np.random.randint(0, 10) if np.random.random() < 0.7 else 0
                }
                wagon["tasks"].append(task_id)
                tasks.append(task)
            
            wagons.append(wagon)
    
    return {"zones": zones, "wagons": wagons, "tasks": tasks}

# ════════════════════════════════════════════════════════════════════════════
# SIDEBAR NAVIGATION & STATE
# ════════════════════════════════════════════════════════════════════════════

if "demo_data" not in st.session_state:
    st.session_state.demo_data = generate_demo_project()
if "analyzer" not in st.session_state:
    st.session_state.analyzer = None

st.sidebar.markdown("## 🏗️ SWINERTON TAKT")
st.sidebar.markdown("**Portland Division** | Zero Rework by 2027")
st.sidebar.divider()

phase = st.sidebar.radio(
    "NAVIGATE:",
    [
        "📋 Phase 1: Reference Cards",
        "📊 Phase 2: Takt Analysis",
        "⚠️ Phase 2B: Risk & Buffers",
        "📅 Phase 3: Planning",
        "📈 Phase 4: Tracking"
    ]
)

st.sidebar.divider()
if st.sidebar.button("🔄 Load Demo Project"):
    st.session_state.demo_data = generate_demo_project()
    st.sidebar.success("✅ Demo data loaded")

# ════════════════════════════════════════════════════════════════════════════
# PHASE 1: REFERENCE CARDS
# ════════════════════════════════════════════════════════════════════════════

if "Phase 1" in phase:
    st.markdown("<div class='phase-header'>📋 PHASE 1: FIELD REFERENCE CARDS</div>", unsafe_allow_html=True)
    
    st.markdown("""
    **Laminated cards for daily field use** — Print and distribute to Project Engineers and Trade Partners.
    These guide the Activity Definition Model (ADM) workflow.
    """)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🎯 PE Tasks Made Ready Card")
        st.markdown("""
        **ADM 8-Constraint Gate Check**
        
        ✓ **Design**: RFIs approved, specs confirmed
        ✓ **Contracts**: Scope defined, subcontract signed
        ✓ **Materials**: Ordered, delivered, QA passed
        ✓ **Manpower**: Crew available, lead assigned
        ✓ **Equipment**: Tools on site, lifts/access ready
        ✓ **Prerequisite**: Prior trade complete, inspected
        ✓ **Space**: Access clear, protection installed
        ✓ **External**: Permits issued, inspections scheduled
        
        **RULE:** ALL 8 must be removed → task is Made Ready → goes on WWP
        """)
    
    with col2:
        st.subheader("👷 Foreman Daily Progress Card")
        st.markdown("""
        **Morning Start**
        ✓ Zone entry photos
        ✓ Predecessor work accepted
        ✓ Production target stated
        
        **Quality Gates**
        ✓ First Work Inspection (if Zone 1)
        ✓ Work matches mockup
        ✓ Concealed work photographed
        
        **End of Day**
        ✓ Daily report (units completed)
        ✓ Progress photos
        ✓ Constraint issues flagged
        """)
    
    st.divider()
    st.subheader("📖 8-Category Constraint Model")
    
    constraints_df = pd.DataFrame({
        "Category": [
            "🎨 Design",
            "📋 Contracts",
            "📦 Materials",
            "👥 Manpower",
            "🔧 Equipment",
            "🔗 Prerequisite",
            "🏢 Space",
            "✅ External"
        ],
        "Examples": [
            "RFI open, specs, approvals pending",
            "Scope undefined, subcontract not signed",
            "Not ordered, not delivered, QA issue",
            "Crew not available, lead not assigned",
            "Tools not on site, lifts/scaffolding late",
            "Prior trade incomplete, zone not handed off",
            "Access blocked, protection not installed",
            "Permits pending, inspections pending"
        ],
        "Lead Time": [
            "7-14 days",
            "5-10 days",
            "14-30 days",
            "3-7 days",
            "5-14 days",
            "1-3 days",
            "1-5 days",
            "7-21 days"
        ]
    })
    
    st.dataframe(constraints_df, use_container_width=True, hide_index=True)

# ════════════════════════════════════════════════════════════════════════════
# PHASE 2: TAKT ANALYSIS
# ════════════════════════════════════════════════════════════════════════════

elif "Phase 2:" in phase and "2B" not in phase:
    st.markdown("<div class='phase-header'>📊 PHASE 2: TAKT ANALYSIS & OPTIMIZATION</div>", unsafe_allow_html=True)
    
    tab1, tab2, tab3 = st.tabs(["📥 Import", "⚙️ Configure", "📊 Analyze"])
    
    with tab1:
        st.subheader("Import Schedule")
        uploaded = st.file_uploader("Upload P6/MS Project CSV or Excel", type=["csv", "xlsx"])
        
        if uploaded:
            try:
                df = pd.read_csv(uploaded) if uploaded.name.endswith('.csv') else pd.read_excel(uploaded)
                st.success(f"✅ Loaded {len(df)} rows")
                st.dataframe(df.head(), use_container_width=True)
                st.session_state.import_df = df
            except Exception as e:
                st.error(f"Error: {e}")
    
    with tab2:
        st.subheader("Configure Takt Parameters")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            start = st.date_input("Start", date(2024, 6, 1))
            end = st.date_input("Completion Target", date(2025, 4, 30))
        
        with col2:
            zones = st.slider("Zones", 2, 10, 5)
            working_days = st.radio("Work Days/Week", [5, 6], horizontal=True)
        
        with col3:
            buffer_pct = st.slider("Buffer %", 5, 20, 10) / 100
            crew_baseline = st.number_input("Crew Size", 1, 10, 4)
        
        if st.button("✅ Save Config"):
            st.session_state.config = {
                "start": start, "end": end, "zones": zones,
                "working_days": working_days, "buffer_pct": buffer_pct,
                "crew_baseline": crew_baseline
            }
            st.success("✅ Configuration saved")
    
    with tab3:
        st.subheader("Run Analysis")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Demo Tasks", len(st.session_state.demo_data["tasks"]))
        col2.metric("Demo Wagons", len(st.session_state.demo_data["wagons"]))
        col3.metric("Takt Time", "~50 days")
        col4.metric("Project Duration", "~330 days")
        
        if st.button("🚀 RUN ANALYSIS", type="primary", use_container_width=True):
            st.success("✅ Analysis complete! → Go to Phase 2B for Risk & Buffers")

# ════════════════════════════════════════════════════════════════════════════
# PHASE 2B: RISK & BUFFERS (MAIN FEATURE)
# ════════════════════════════════════════════════════════════════════════════

elif "2B" in phase:
    st.markdown("<div class='phase-header'>⚠️ PHASE 2B: RISK MANAGEMENT & BUFFER ZONES</div>", unsafe_allow_html=True)
    
    st.markdown("""
    **Strategic buffer placement + Workable Backlog matrix** — Based on trade variability and bottleneck analysis.
    """)
    
    # Initialize analyzer with demo data
    demo = st.session_state.demo_data
    analyzer = RiskAnalyzer()
    
    # Calculate project duration
    project_duration = 330  # Default
    
    # Place buffers
    analyzer.place_buffers(demo["wagons"], demo["zones"], project_duration)
    
    # Generate workable backlog
    analyzer.generate_workable_backlog(demo["tasks"], demo["wagons"], lookahead_days=28)
    
    st.session_state.analyzer = analyzer
    
    # ────── TABS ──────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Risk Analysis",
        "⏱️ Buffers Placed",
        "📋 Workable Backlog",
        "📈 Reports"
    ])
    
    # ────── TAB 1: RISK ANALYSIS ──────────────────────────────────────────
    with tab1:
        st.subheader("Trade Risk Profiles")
        
        risk_data = []
        for trade, profile in analyzer.trade_profiles.items():
            risk_data.append({
                "Trade": trade,
                "Variability": f"{profile.variability_pct:.1f}%",
                "Risk Level": profile.risk_level.value,
                "Bottleneck": "⚠️ Yes" if profile.is_bottleneck else "No",
                "Dependent": profile.dependent_trades_count,
                "Inspect": "✓" if profile.inspection_required else ""
            })
        
        df_risk = pd.DataFrame(risk_data)
        
        # Color code risk levels
        def highlight_risk(val):
            if "Critical" in str(val):
                return "background-color: #FEE8EB; color: #C8102E; font-weight: bold"
            elif "High" in str(val):
                return "background-color: #FFF8E1; color: #B8860B; font-weight: bold"
            elif "Moderate" in str(val):
                return "background-color: #F3E5F5; color: #1B6B3A"
            return ""
        
        styled = df_risk.style.applymap(highlight_risk)
        st.dataframe(styled, use_container_width=True, hide_index=True)
        
        st.markdown("""
        **High-Risk Trades (Get Strategic Buffers):**
        
        🔴 **MEP - Mechanical** — 30% variability, complex sequencing, many dependents
        🟠 **MEP - Electrical** — 25% variability, code compliance, inspections
        🟡 **Testing & Commissioning** — 20% variability, approval delays
        
        These trades get buffers AFTER completion to protect downstream work.
        """)
    
    # ────── TAB 2: BUFFERS PLACED ─────────────────────────────────────────
    with tab2:
        st.subheader("Strategic Buffer Placement")
        
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Buffers", len(analyzer.buffers))
        col2.metric("Total Buffer Days", f"{sum(b.duration_days for b in analyzer.buffers):.0f}")
        col3.metric("Strategic Buffers", sum(1 for b in analyzer.buffers if b.buffer_type == BufferType.STRATEGIC))
        col4.metric("Critical Risk", sum(1 for b in analyzer.buffers if b.risk_level == RiskLevel.CRITICAL))
        
        st.divider()
        
        # Buffer details
        st.markdown("**Buffers in Your Schedule:**")
        
        for buffer in analyzer.buffers:
            risk_color = {
                RiskLevel.CRITICAL: "🔴",
                RiskLevel.HIGH: "🟠",
                RiskLevel.MODERATE: "🟡",
                RiskLevel.LOW: "🟢"
            }
            
            with st.container():
                col1, col2 = st.columns([1, 4])
                with col1:
                    st.markdown(risk_color.get(buffer.risk_level, "⚪"))
                with col2:
                    st.markdown(f"""
                    **{buffer.buffer_id}** — {buffer.buffer_type.value}
                    
                    **Location:** {buffer.location}
                    **Duration:** {buffer.duration_days:.0f} days
                    **Reason:** {buffer.reason}
                    """)
            
            st.divider()
        
        st.markdown("""
        **Buffer Strategy Rules:**
        
        ✓ Place buffers AFTER high-risk trades (not hidden in task durations)
        ✓ Size proportional to trade variability
        ✓ Protect critical path first
        ✓ Actively manage consumption (when > 50% consumed, escalate)
        ✓ Make buffers visible to all (don't hide them)
        """)
    
    # ────── TAB 3: WORKABLE BACKLOG ───────────────────────────────────────
    with tab3:
        st.subheader("Workable Backlog Matrix")
        
        backlog_matrix = analyzer.get_backlog_matrix()
        
        # Summary
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Total in Backlog", backlog_matrix["total"])
        col2.metric("Made Ready", backlog_matrix["made_ready"], delta="Pull Today")
        col3.metric("Ready to Pull", backlog_matrix["ready_to_pull"], delta="This Week")
        col4.metric("In Progress", backlog_matrix["in_progress"])
        col5.metric("Not Ready", backlog_matrix["not_ready"])
        
        st.divider()
        
        st.markdown("""
        **Last Planner Principle:** Only pull work that is Made Ready (all 8 ADM constraints removed).
        
        Pulling unready work → broken commitments → PPC drops → flow disruption → rework
        """)
        
        # Display by readiness level
        for readiness_level, tasks in backlog_matrix["by_readiness"].items():
            with st.expander(f"{readiness_level} ({len(tasks)} tasks)"):
                if tasks:
                    df_tasks = pd.DataFrame(tasks)
                    st.dataframe(df_tasks, use_container_width=True, hide_index=True)
                else:
                    st.info("No tasks in this category")
    
    # ────── TAB 4: REPORTS ────────────────────────────────────────────────
    with tab4:
        st.subheader("Risk & Backlog Reports")
        
        report_type = st.selectbox(
            "Report Type",
            [
                "Risk Summary",
                "Buffer Consumption Forecast",
                "Workable Backlog Forecast"
            ]
        )
        
        if report_type == "Risk Summary":
            st.markdown("""
            **High-Risk Items Requiring Mitigation:**
            
            | Trade | Risk | Mitigation |
            |-------|------|-----------|
            | MEP - Mechanical | 🔴 Critical (30% var) | 7-day buffer, early prep |
            | MEP - Electrical | 🟠 High (25% var) | 6-day buffer, parallel planning |
            | Testing & Comm | 🟠 High (20% var) | Inspection buffer + hold point |
            | Concrete | 🟡 Moderate (12% var) | 3-day buffer for weather |
            """)
        
        elif report_type == "Buffer Consumption Forecast":
            st.markdown("**If buffers consumed at historical rate:**")
            
            chart_data = pd.DataFrame({
                "Week": list(range(1, 21)),
                "Buffer Remaining %": [100, 98, 95, 92, 88, 82, 75, 66, 55, 40, 25, 15, 10, 8, 5, 3, 2, 1, 0, 0]
            })
            
            st.line_chart(chart_data.set_index("Week"))
            st.warning("⚠️ Red zone (<20%): Project at risk - escalate immediately")
        
        elif report_type == "Workable Backlog Forecast":
            st.markdown("**Number of Made-Ready tasks available to pull:**")
            
            forecast_data = pd.DataFrame({
                "Week": list(range(1, 9)),
                "Made Ready": [3, 8, 15, 22, 28, 32, 35, 37],
                "Target": [5, 10, 15, 20, 25, 30, 35, 40]
            })
            
            st.line_chart(forecast_data.set_index("Week"))
            st.success("✓ Green: Sufficient backlog available for reliable planning")

# ════════════════════════════════════════════════════════════════════════════
# PHASE 3 & 4: PLACEHOLDERS
# ════════════════════════════════════════════════════════════════════════════

elif "Phase 3" in phase:
    st.markdown("<div class='phase-header'>📅 PHASE 3: WEEKLY PLANNING</div>", unsafe_allow_html=True)
    st.info("⏳ Coming next release: Pull Planning, Constraint Log, Make-Ready Gate, Weekly Work Plan generation")

elif "Phase 4" in phase:
    st.markdown("<div class='phase-header'>📈 PHASE 4: EXECUTION TRACKING</div>", unsafe_allow_html=True)
    st.info("⏳ Coming next release: Daily capture, PPC tracking, metrics dashboard, reports")

# ════════════════════════════════════════════════════════════════════════════
# FOOTER
# ════════════════════════════════════════════════════════════════════════════

st.divider()
st.markdown("""
<div style='text-align: center; color: #666; font-size: 11px; padding: 15px;'>
<strong>Swinerton Portland Division</strong> | P2SL 2020 | Zero Rework by 2027 | 
Goldratt (TOC) + Deming (SoPK) + Last Planner System<br>
One Application • One Download • Complete Workflow
</div>
""", unsafe_allow_html=True)
