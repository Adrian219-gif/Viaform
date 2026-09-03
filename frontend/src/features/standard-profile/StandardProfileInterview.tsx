"use client";

import { useMemo, useRef, useState } from "react";
import styles from "../../app/page.module.css";
import { MaterialStatus, ProfileIssue, ScoreWithScale, STANDARD_PROFILE_STEPS, StandardUserProfile, canProceedToExplore, profileCompleteness } from "./profile";
import { CachedProfileStatus, STANDARD_PROFILE_MODULE_STEPS, StandardProfileModule, mergeProfileModule } from "./profile-cache";

const STEPS = STANDARD_PROFILE_STEPS;
const MODULES: Array<{ id: StandardProfileModule; label: string; step: number }> = [
  { id: "university", label: "本科院校", step: STANDARD_PROFILE_MODULE_STEPS.university }, { id: "major", label: "本科专业", step: STANDARD_PROFILE_MODULE_STEPS.major },
  { id: "academic", label: "学术成绩", step: STANDARD_PROFILE_MODULE_STEPS.academic }, { id: "language", label: "语言考试", step: STANDARD_PROFILE_MODULE_STEPS.language },
  { id: "standardized", label: "标化考试", step: STANDARD_PROFILE_MODULE_STEPS.standardized }, { id: "materials", label: "申请材料", step: STANDARD_PROFILE_MODULE_STEPS.materials },
];
const MATERIAL_OPTIONS: Array<{ value: Exclude<MaterialStatus, null>; label: string }> = [
  { value: "prepared", label: "已准备" }, { value: "not_prepared", label: "未准备" },
  { value: "unknown", label: "不确定" }, { value: "not_applicable", label: "不适用" },
];
const DEGREE_CERTIFICATE_OPTIONS: Array<{ value: "prepared" | "not_prepared" | "unknown"; label: string }> = [
  { value: "prepared", label: "已有" }, { value: "not_prepared", label: "暂无" },
  { value: "unknown", label: "不确定" },
];
type EntryView = "interview" | "summary" | "incomplete";
type View = EntryView | "modules" | "edit";

type Props = {
  profile: StandardUserProfile;
  profileStatus: CachedProfileStatus;
  entryView: EntryView;
  onDraftChange: (profile: StandardUserProfile) => void;
  onSave: (profile: StandardUserProfile, status: CachedProfileStatus) => void;
  onExplore: (status: CachedProfileStatus) => void;
};

function numeric(value: string): number | null { return value === "" ? null : Number(value); }
function cloneProfile(profile: StandardUserProfile): StandardUserProfile { return structuredClone(profile); }

export default function StandardProfileInterview({ profile, profileStatus, entryView, onDraftChange, onSave, onExplore }: Props) {
  const firstMissing = profileCompleteness(profile)[0]?.step ?? (STEPS.length - 1);
  const [view, setView] = useState<View>(entryView);
  const [step, setStep] = useState(entryView === "interview" ? firstMissing : 0);
  const [draft, setDraft] = useState(() => cloneProfile(profile));
  const [editingModule, setEditingModule] = useState<StandardProfileModule | null>(null);
  const [gpaScaleChoice, setGpaScaleChoice] = useState(() => gpaScale(profile));
  const firstFieldRef = useRef<HTMLInputElement>(null);
  const progress = Math.round((step / (STEPS.length - 1)) * 100);
  const missingItems = useMemo(() => profileCompleteness(draft), [draft]);
  const isEditing = view === "edit";

  function update(next: Partial<StandardUserProfile>) {
    const updated = { ...draft, ...next };
    setDraft(updated);
    if (!isEditing) onDraftChange(updated);
  }
  function updateEducation(next: Partial<StandardUserProfile["education"]>) { update({ education: { ...draft.education, ...next } }); }
  function updateLanguage(next: Partial<StandardUserProfile["language"]>) { update({ language: { ...draft.language, ...next } }); }
  function updateTests(next: Partial<StandardUserProfile["standardized_test"]>) { update({ standardized_test: { ...draft.standardized_test, ...next } }); }
  function updateMaterials(next: Partial<StandardUserProfile["materials"]>) { update({ materials: { ...draft.materials, ...next } }); }
  function setScore(kind: "gpa" | "average_score", part: keyof ScoreWithScale, value: number | null) {
    const current = draft.education[kind] ?? { value: null, scale: null };
    updateEducation({ [kind]: { ...current, [part]: value } });
  }

  function finishInitial() {
    if (!canProceedToExplore(draft, "complete")) {
      setStep(missingItems[0].step);
      requestAnimationFrame(() => firstFieldRef.current?.focus());
      return;
    }
    onSave(draft, "completed");
    onExplore("completed");
  }

  function beginEdit(module: StandardProfileModule, moduleStep: number) {
    setEditingModule(module);
    setDraft(cloneProfile(profile));
    setGpaScaleChoice(gpaScale(profile));
    setStep(moduleStep);
    setView("edit");
  }
  function cancelEdit() { setDraft(cloneProfile(profile)); setEditingModule(null); setView("modules"); }
  function saveEdit() {
    if (!editingModule) return;
    const merged = mergeProfileModule(profile, draft, editingModule);
    onSave(merged, "completed");
    setDraft(cloneProfile(merged));
    setEditingModule(null);
    setView("modules");
  }
  function finishUpdates() {
    const nextIssues = profileCompleteness(profile);
    if (nextIssues.length) {
      setDraft(cloneProfile(profile));
      setStep(nextIssues[0].step);
      setView("interview");
      return;
    }
    onSave(profile, "completed");
    setView("summary");
  }
  function resumeIncomplete() {
    const nextIssues = profileCompleteness(draft);
    setStep(nextIssues[0]?.step ?? (STEPS.length - 1));
    setView("interview");
  }
  function next() { setStep((current) => Math.min(current + 1, STEPS.length - 1)); }
  function previous() { setStep((current) => Math.max(current - 1, 0)); }
  function statusButtons(value: "has_value" | "none" | "unknown" | null, setValue: (value: "has_value" | "none" | "unknown") => void) {
    return <div className={styles.profileChoiceRow}>{[["has_value", "有正式成绩"], ["none", "没有正式成绩"], ["unknown", "不确定 / 不记得"]].map(([option, label]) => <button type="button" key={option} className={value === option ? styles.profileChoiceActive : ""} onClick={() => setValue(option as "has_value" | "none" | "unknown")}>{label}</button>)}</div>;
  }

  if (view === "summary" || view === "modules" || view === "incomplete") {
    return <ProfileLanding profile={profile} incomplete={view === "incomplete"} modulesMode={view === "modules"} issues={profileCompleteness(profile)} onContinue={() => onExplore(profileStatus === "completed" ? "completed" : "skipped")} onUpdate={() => setView("modules")} onEdit={beginEdit} onFinishUpdates={finishUpdates} onResume={resumeIncomplete} />;
  }

  return <main className={styles.page}><header className={styles.header}><div className={styles.brand}>Viaform</div><span className={styles.status}>{isEditing ? "更新背景信息" : "标准背景信息 · 不调用 AI"}</span></header><div className={styles.workspace}>
    <aside className={styles.sidebar} aria-label="访谈进度"><div><p className={styles.eyebrow}>STANDARD USER PROFILE</p><h1>{isEditing ? `修改${STEPS[step]}` : "先建立可复用的申请背景"}</h1><p className={styles.sidebarIntro}>这里只记录通用事实，不判断是否满足任何具体项目要求。</p></div>{!isEditing && <><div className={styles.progressBlock}><div className={styles.progressMeta}><span>完成进度</span><strong>{progress}%</strong></div><div className={styles.progressTrack}><span style={{ width: `${progress}%` }} /></div></div><ol className={styles.steps}>{STEPS.map((label, index) => <li key={label} className={index < step ? styles.done : index === step ? styles.active : ""}><span>{index < step ? "✓" : index + 1}</span><div><strong>{label}</strong><small>{index < step ? "已查看" : index === step ? "进行中" : "待填写"}</small></div></li>)}</ol></>}<p className={styles.privacy}>Ask once · 后续按项目要求补充特殊信息</p></aside>
    <section className={styles.chat} aria-label="标准背景信息访谈"><div className={styles.chatHeader}><div className={styles.advisorAvatar} aria-hidden="true" /><div><strong>Viaform</strong><span><i /> 正在记录通用用户事实</span></div><span className={styles.stepCount}>{isEditing ? "单项修改" : `${step + 1} / ${STEPS.length}`}</span></div><div className={styles.messages} aria-live="polite"><div className={styles.dayLabel}>今天</div>
      {step === 0 && <><div className={styles.welcome}><span>👋</span><div><strong>先完成一轮标准背景信息</strong><p>不会询问具体项目的课程、学分或资格条件。</p>{!isEditing && <button type="button" className={styles.skipProfileAction} onClick={() => { onSave(draft, "skipped"); onExplore("skipped"); }}>暂时跳过，直接查看院校和项目 →</button>}</div></div><Question text="你的本科院校是什么？" /></>}
      {step === 1 && <Question text="你的本科专业是什么？" />}{step === 2 && <Question text="请提供 GPA 或平均分，至少填写一种。" />}{step === 3 && <Question text="你目前有 IELTS 或 TOEFL 正式成绩吗？" />}{step === 4 && <Question text="你目前有 GRE 或 GMAT 正式成绩吗？" />}{step === 5 && <Question text="请记录你目前已有的标准申请材料。" />}{step === 6 && <Question text="确认信息完整后，即可进入院校筛选。" />}
      <div className={styles.profileStructuredCard}>
        {step === 0 && <label><span>本科院校</span><input ref={firstFieldRef} value={draft.education.university} onChange={(event) => updateEducation({ university: event.target.value })} placeholder="例如：中山大学" /></label>}
        {step === 1 && <label><span>本科专业</span><input ref={firstFieldRef} value={draft.education.major} onChange={(event) => updateEducation({ major: event.target.value })} placeholder="例如：软件工程" /></label>}
        {step === 2 && <AcademicFields profile={draft} gpaScaleChoice={gpaScaleChoice} setGpaScaleChoice={setGpaScaleChoice} setScore={setScore} />}
        {step === 3 && <div className={styles.profileSectionStack}>{(["IELTS", "TOEFL"] as const).map((exam) => <fieldset key={exam}><legend>{exam}</legend>{statusButtons(draft.language[`${exam}_status`], (status) => updateLanguage({ [`${exam}_status`]: status, ...(status === "has_value" ? {} : { [exam]: null }) }))}{draft.language[`${exam}_status`] === "has_value" && <><label><span>{exam} 总分</span><input type="number" min="0" step="any" value={draft.language[exam] ?? ""} onChange={(event) => updateLanguage({ [exam]: numeric(event.target.value) })} /></label>{exam === "IELTS" && <Subscores values={draft.language.IELTS_subscores} onChange={(part, value) => updateLanguage({ IELTS_subscores: { ...draft.language.IELTS_subscores, [part]: value } })} />}{exam === "TOEFL" && <Subscores values={draft.language.TOEFL_subscores} onChange={(part, value) => updateLanguage({ TOEFL_subscores: { ...draft.language.TOEFL_subscores, [part]: value } })} />}</>}</fieldset>)}</div>}
        {step === 4 && <div className={styles.profileSectionStack}>{(["GRE", "GMAT"] as const).map((exam) => <fieldset key={exam}><legend>{exam}</legend>{statusButtons(draft.standardized_test[`${exam}_status`], (status) => updateTests({ [`${exam}_status`]: status, ...(status === "has_value" ? {} : { [exam]: null }) }))}{draft.standardized_test[`${exam}_status`] === "has_value" && <label><span>{exam} 实际成绩</span><input type="number" min="0" step="any" value={draft.standardized_test[exam] ?? ""} onChange={(event) => updateTests({ [exam]: numeric(event.target.value) })} /></label>}</fieldset>)}</div>}
        {step === 5 && <div className={styles.profileSectionStack}>{([ ["cv_status", "CV / Resume"], ["transcript_status", "成绩单"], ["motivation_letter_status", "SOP / Personal Statement / Motivation Letter"], ["portfolio_status", "作品集"] ] as const).map(([key, label]) => <fieldset key={key}><legend>{label}</legend><div className={styles.profileChoiceRow}>{MATERIAL_OPTIONS.map((option) => <button type="button" key={option.value} className={draft.materials[key] === option.value ? styles.profileChoiceActive : ""} onClick={() => updateMaterials({ [key]: option.value })}>{option.label}</button>)}</div></fieldset>)}<fieldset><legend>你目前是否已有学位证？</legend><div className={styles.profileChoiceRow}>{DEGREE_CERTIFICATE_OPTIONS.map((option) => <button type="button" key={option.value} className={draft.materials.degree_certificate_status === option.value ? styles.profileChoiceActive : ""} onClick={() => updateMaterials({ degree_certificate_status: option.value })}>{option.label}</button>)}</div></fieldset><label><span>目前已确认愿意提供推荐信的推荐人数量</span><input type="number" min="0" step="1" value={draft.materials.confirmed_recommenders ?? ""} onChange={(event) => updateMaterials({ confirmed_recommenders: numeric(event.target.value) })} /></label></div>}
        {step === 6 && <div className={styles.profileReview}><p>系统会检查是否回答了标准背景信息；“没有”与“不确定”都属于有效回答。</p><button type="button" className={styles.primaryAction} onClick={finishInitial}>完成背景信息 / 进入院校筛选</button></div>}
        {missingItems.length > 0 && <div className={styles.profileMissing} role="alert"><strong>还有 {missingItems.length} 项背景信息未完成：</strong><ul>{missingItems.map((issue) => <li key={issue.key}>{issue.label}</li>)}</ul><button type="button" onClick={() => setStep(missingItems[0].step)}>返回补充</button></div>}
      </div></div>{isEditing ? <div className={styles.profileInterviewActions}><button type="button" className={styles.secondaryAction} onClick={cancelEdit}>取消</button><button type="button" className={styles.primaryAction} onClick={saveEdit}>保存修改</button></div> : <div className={styles.profileInterviewActions}>{step > 0 && <button type="button" className={styles.secondaryAction} onClick={previous}>上一步</button>}<span />{step < STEPS.length - 1 && <button type="button" className={styles.primaryAction} onClick={next}>下一步</button>}</div>}</section>
  </div></main>;
}

function gpaScale(profile: StandardUserProfile): string { const scale = profile.education.gpa?.scale; return scale === 3 || scale === 4 || scale === 5 ? String(scale) : scale ? "other" : ""; }
function AcademicFields({ profile, gpaScaleChoice, setGpaScaleChoice, setScore }: { profile: StandardUserProfile; gpaScaleChoice: string; setGpaScaleChoice: (value: string) => void; setScore: (kind: "gpa" | "average_score", part: keyof ScoreWithScale, value: number | null) => void }) {
  return <div className={styles.profileScoreGrid}><fieldset><legend>GPA（可选）</legend><label><span>先选择 GPA 分制</span><select value={gpaScaleChoice} onChange={(event) => { const choice = event.target.value; setGpaScaleChoice(choice); setScore("gpa", "scale", choice && choice !== "other" ? Number(choice) : null); }}><option value="">请选择</option><option value="3">3.0</option><option value="4">4.0</option><option value="5">5.0</option><option value="other">其他</option></select></label>{gpaScaleChoice === "other" && <label><span>GPA 满分</span><input type="number" min="0" step="any" value={profile.education.gpa?.scale ?? ""} onChange={(event) => setScore("gpa", "scale", numeric(event.target.value))} /></label>}<label><span>你的 GPA</span><input type="number" min="0" step="any" disabled={!profile.education.gpa?.scale} value={profile.education.gpa?.value ?? ""} onChange={(event) => setScore("gpa", "value", numeric(event.target.value))} placeholder={profile.education.gpa?.scale ? `不超过 ${profile.education.gpa.scale}` : "请先选择分制"} /></label>{profile.education.gpa?.value !== null && profile.education.gpa?.value !== undefined && profile.education.gpa.scale !== null && profile.education.gpa.value > profile.education.gpa.scale && <p className={styles.profileFieldError}>GPA 不能高于所选分制，请检查。</p>}</fieldset><fieldset><legend>平均分（可选）</legend><label><span>平均分</span><input type="number" min="0" step="any" value={profile.education.average_score?.value ?? ""} onChange={(event) => setScore("average_score", "value", numeric(event.target.value))} placeholder="例如：86" /></label><label><span>平均分满分</span><input type="number" min="0" step="any" value={profile.education.average_score?.scale ?? ""} onChange={(event) => setScore("average_score", "scale", numeric(event.target.value))} placeholder="例如：100" /></label></fieldset></div>;
}
function Subscores({ values, onChange }: { values: Record<string, number | null>; onChange: (part: string, value: number | null) => void }) { return <div className={styles.profileCompactGrid}>{Object.keys(values).map((part) => <label key={part}><span>{part}</span><input type="number" min="0" step="any" value={values[part] ?? ""} onChange={(event) => onChange(part, numeric(event.target.value))} placeholder="可留空" /></label>)}</div>; }
function examSummary(status: "has_value" | "none" | "unknown" | null, score: number | null): string { if (status === "has_value") return score === null ? "成绩未填写" : String(score); if (status === "none") return "没有正式成绩"; if (status === "unknown") return "不确定"; return "未回答"; }
function summary(profile: StandardUserProfile, module: StandardProfileModule): string {
  if (module === "university") return profile.education.university || "未填写";
  if (module === "major") return profile.education.major || "未填写";
  if (module === "academic") return [profile.education.gpa && `GPA ${profile.education.gpa.value ?? "?"}/${profile.education.gpa.scale ?? "?"}`, profile.education.average_score && `均分 ${profile.education.average_score.value ?? "?"}/${profile.education.average_score.scale ?? "?"}`].filter(Boolean).join(" · ") || "未填写";
  if (module === "language") return `IELTS：${examSummary(profile.language.IELTS_status, profile.language.IELTS)} · TOEFL：${examSummary(profile.language.TOEFL_status, profile.language.TOEFL)}`;
  if (module === "standardized") return `GRE：${examSummary(profile.standardized_test.GRE_status, profile.standardized_test.GRE)} · GMAT：${examSummary(profile.standardized_test.GMAT_status, profile.standardized_test.GMAT)}`;
  return `CV：${profile.materials.cv_status ?? "未填写"} · 学位证：${profile.materials.degree_certificate_status ?? "未填写"} · 推荐人：${profile.materials.confirmed_recommenders ?? "未填写"}`;
}
function ProfileLanding({ profile, incomplete, modulesMode, issues, onContinue, onUpdate, onEdit, onFinishUpdates, onResume }: { profile: StandardUserProfile; incomplete: boolean; modulesMode: boolean; issues: ProfileIssue[]; onContinue: () => void; onUpdate: () => void; onEdit: (module: StandardProfileModule, step: number) => void; onFinishUpdates: () => void; onResume: () => void }) {
  return <main className={`${styles.page} ${styles.profilePage}`}><header className={styles.header}><div className={styles.brand}>Viaform</div><span className={styles.status}>{modulesMode ? "更新背景信息" : "已有背景信息"}</span></header><section className={styles.profileShell}><div className={styles.profileHeading}><span className={styles.successBadge}>{incomplete ? "背景信息尚未完成" : modulesMode ? "选择要更新的模块" : "PROFILE READY"}</span><h1>{modulesMode ? "更新标准背景信息" : incomplete ? "继续完善背景信息" : "继续使用已有信息"}</h1><p>{incomplete ? `还有 ${issues.length} 项必填信息未完成。` : "已读取本机保存的 Standard User Profile。"}</p></div><div className={styles.profileModuleList}>{MODULES.map((module) => <article key={module.id}><div><strong>{module.label}</strong><p>{summary(profile, module.id)}</p></div>{modulesMode && <button type="button" className={styles.secondaryAction} onClick={() => onEdit(module.id, module.step)}>修改</button>}</article>)}</div>{incomplete && <div className={styles.profileMissing}><strong>尚未完成：</strong><ul>{issues.map((issue) => <li key={issue.key}>{issue.label}</li>)}</ul></div>}<div className={styles.profileActions}>{modulesMode ? <><button type="button" className={styles.secondaryAction} onClick={onContinue}>暂时返回院校筛选</button><button type="button" className={styles.primaryAction} onClick={onFinishUpdates}>完成更新</button></> : incomplete ? <><button type="button" className={styles.secondaryAction} onClick={onContinue}>暂时继续浏览</button><button type="button" className={styles.primaryAction} onClick={onResume}>继续补充</button></> : <><button type="button" className={styles.secondaryAction} onClick={onUpdate}>更新背景信息</button><button type="button" className={styles.primaryAction} onClick={onContinue}>继续使用已有信息</button></>}</div></section></main>;
}
function Question({ text }: { text: string }) { return <div className={styles.assistantRow}><div className={styles.miniAvatar} aria-hidden="true" /><p>{text}</p></div>; }
