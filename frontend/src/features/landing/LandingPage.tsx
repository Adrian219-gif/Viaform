import styles from "./LandingPage.module.css";

type Props = {
  onStart: () => void;
};

const steps = [
  ["01", "建立申请画像", "用结构化信息整理学术背景、考试成绩与申请材料。"],
  ["02", "定位目标项目与官方要求", "从院校探索进入具体项目，并整理可追溯的申请要求。"],
  ["03", "生成 Gap Analysis 与 Action Plan", "对照已有背景识别差距，形成清晰的下一步行动。"],
] as const;

export default function LandingPage({ onStart }: Props) {
  return (
    <main className={styles.landing}>
      <header className={styles.header}>
        <a className={styles.brand} href="#product" aria-label="Viaform home">Viaform</a>
        <nav aria-label="首页导航">
          <a href="#product">Product</a>
          <a href="#how-it-works">How it works</a>
          <a href="https://github.com/Adrian219-gif/UniversityApplyPlan" target="_blank" rel="noreferrer">GitHub</a>
        </nav>
        <button className={styles.headerCta} type="button" onClick={onStart}>开始规划 <span>↗</span></button>
      </header>

      <section className={styles.hero} id="product">
        <p className={styles.eyebrow}>AI-ASSISTED APPLICATION PLANNING</p>
        <h1>从申请背景到行动计划，<em>把复杂信息变得清晰。</em></h1>
        <p className={styles.heroCopy}>基于你的真实背景与目标项目要求，完成结构化 Gap Analysis，并整理可执行的申请准备路径。</p>
        <button className={styles.primaryCta} type="button" onClick={onStart}>开始规划 <span>→</span></button>
      </section>

      <section className={styles.workflow} id="how-it-works">
        <div className={styles.sectionHeading}>
          <p className={styles.eyebrow}>HOW IT WORKS</p>
          <h2>三个步骤，建立你的申请路径</h2>
        </div>
        <div className={styles.stepGrid}>
          {steps.map(([index, title, description]) => (
            <article key={index}>
              <span>{index}</span>
              <h3>{title}</h3>
              <p>{description}</p>
            </article>
          ))}
        </div>
      </section>

      <section className={styles.preview} aria-labelledby="preview-title">
        <p className={styles.eyebrow}>FROM REQUIREMENTS TO ACTION</p>
        <h2 id="preview-title">从项目要求，<br />到可执行的申请计划</h2>
        <p>结合你的申请背景、目标项目官方要求与申请时间线，识别差距，并倒推出下一步行动。</p>
      </section>

      <footer className={styles.footer}>Viaform</footer>

    </main>
  );
}
