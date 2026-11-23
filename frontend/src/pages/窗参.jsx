import React, { useEffect, useState } from "react";
import { 取, 递 } from "../api.js";

export default function 窗参页() {
  const [规, 设规] = useState(null);
  const [桩, 设桩] = useState([]);
  const [型, 设型] = useState(null);
  const [史, 设史] = useState([]);
  const [表, 设表] = useState({ 窗型: "滑动", 窗长秒: 60, 滑动步长秒: 30 });
  const [讯, 设讯] = useState("");
  const [查, 设查] = useState({ 事件时: "2026-11-22T12:10:10Z", 房间键: "房A" });
  const [集, 设集] = useState(null);
  const [演, 设演] = useState(null);

  const 刷 = () => {
    取("/站规").then(设规);
    取("/空桩").then(设桩);
    取("/窗型").then(设型);
    取("/窗参史").then(设史);
  };
  useEffect(() => { 刷(); }, []);

  const 改参 = async () => {
    设讯("");
    try {
      const 体 = { 窗型: 表.窗型, 窗长秒: Number(表.窗长秒) };
      if (表.窗型 === "滑动") 体.滑动步长秒 = Number(表.滑动步长秒);
      const r = await 递("/窗参", 体);
      设讯(r.已变更 ? `已换代：g${r.窗代}（${r.窗型} ${r.窗长秒}/${r.滑动步长秒}）` : `未变：${r.说明}`);
      刷();
    } catch (e) {
      设讯(`失败闭：${e.message}`);
    }
  };
  const 排水 = async () => {
    设讯("");
    try {
      const r = await 递("/排水", {});
      设讯(`排水完成：${r.排水.map((x) => `${x.房间键}关${x.新关窗}窗`).join("，")}`);
      刷();
    } catch (e) {
      设讯(`失败闭：${e.message}`);
    }
  };
  const 查集 = async () => {
    设集(null);
    try {
      设集(await 取(`/窗键集?事件时=${encodeURIComponent(查.事件时)}&房间键=${encodeURIComponent(查.房间键)}`));
    } catch (e) {
      设集({ 错误: e.message });
    }
  };
  const 演练 = async () => {
    设演({ 步骤: [], 核查: [], 结论: "运行中…" });
    设演(await 递("/演练/改步长并发"));
    刷();
  };

  if (!规 || !型) return <p className="讯">加载中…</p>;
  const 主参 = ["窗型", "窗长秒", "滑动步长秒", "窗代", "允许迟到秒", "窗归属口径", "关窗条件", "旁路条件"];
  return (
    <div>
      <h1 className="题">窗参</h1>
      <p className="述">
        全局唯一窗格引擎：窗起按<strong>滑动步长</strong>对齐；翻滚=步长等于窗长（每事件恰 1 窗），
        滑动=步长小于窗长（每事件恰落 窗长/步长 窗，多窗归属）。改窗型或改步长：
        有开启窗则<strong>失败闭</strong>；排水后换代，旧窗键带旧窗代明确隔离，绝不同房双套窗键。
      </p>

      <div className="段">
        <div className="段题">当前窗型（只读接口）</div>
        <div className="格">
          <div className="卡"><b>{型.窗型}</b><span>窗型</span></div>
          <div className="卡"><b>{型.窗长秒}s</b><span>窗长</span></div>
          <div className="卡"><b>{型.滑动步长秒}s</b><span>滑动步长</span></div>
          <div className="卡"><b>g{型.窗代}</b><span>窗代</span></div>
          <div className="卡"><b>{型.每事件窗数 ?? "—"}</b><span>每事件窗数</span></div>
          <div className="卡">
            <b><span className={`徽章 ${型.valid ? "通" : "败"}`}>{型.valid ? "valid" : "失效"}</span></b>
            <span>{型.valid ? "窗参一致" : (型.问题 || []).join("；")}</span>
          </div>
        </div>
      </div>

      <div className="段">
        <div className="段题">改窗参（换代）</div>
        <div className="行">
          <select value={表.窗型} onChange={(e) => 设表({ ...表, 窗型: e.target.value })}>
            <option value="翻滚">翻滚</option>
            <option value="滑动">滑动</option>
          </select>
          <label>窗长秒 <input type="number" value={表.窗长秒} onChange={(e) => 设表({ ...表, 窗长秒: e.target.value })} style={{ width: "6rem" }} /></label>
          {表.窗型 === "滑动" && (
            <label>滑动步长秒 <input type="number" value={表.滑动步长秒} onChange={(e) => 设表({ ...表, 滑动步长秒: e.target.value })} style={{ width: "6rem" }} /></label>
          )}
          <button className="水" onClick={改参}>换代生效</button>
          <button className="次" onClick={排水}>排水清场</button>
          <button className="次" onClick={演练}>跑改步长并发演练</button>
        </div>
        {讯 && <div className="报箱 码">{讯}</div>}
        {演 && (
          <div className="报箱 码">
            {`演练结论：${演.结论}\n`}
            {(演.步骤 || []).map((s, i) => `${i + 1}. ${s.步骤} → ${typeof s.结果 === "string" ? s.结果 : JSON.stringify(s.结果, null, 0)}\n`)}
            {(演.核查 || []).map((c) => `${c.通过 ? "✓" : "✗"} ${c.项}${c.注 ? `（${c.注}）` : ""}`).join("\n")}
          </div>
        )}
      </div>

      <div className="段">
        <div className="段题">事件窗键集查询（只读接口）</div>
        <div className="行">
          <label>房间键 <input value={查.房间键} onChange={(e) => 设查({ ...查, 房间键: e.target.value })} style={{ width: "6rem" }} /></label>
          <label>事件时 <input value={查.事件时} onChange={(e) => 设查({ ...查, 事件时: e.target.value })} style={{ width: "13rem" }} /></label>
          <button className="次" onClick={查集}>查窗键集</button>
        </div>
        {集 && (
          <div className="报箱 码">
            {集.错误 ? 集.错误 : `${集.窗型} g${集.窗代} · ${集.窗数} 窗（步长${集.滑动步长秒}s）\n${集.事件窗键集.join("\n")}`}
          </div>
        )}
      </div>

      <div className="段">
        <div className="段题">窗参史（各代隔离留痕）</div>
        <table>
          <thead><tr><th>代</th><th>窗型</th><th>窗长秒</th><th>滑动步长秒</th><th>生效处理时</th><th>备注</th></tr></thead>
          <tbody>
            {史.map((s) => (
              <tr key={s.代}><td>g{s.代}</td><td>{s.窗型}</td><td>{s.窗长秒}</td><td>{s.滑动步长秒}</td><td className="码">{s.生效处理时}</td><td>{s.备注}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="段">
        <div className="段题">主链参数</div>
        <table>
          <thead><tr><th>键</th><th>值</th></tr></thead>
          <tbody>
            {主参.filter((k) => 规[k] != null).map((k) => (
              <tr key={k}><td>{k}</td><td className="码">{规[k]}</td></tr>
            ))}
            {Object.entries(规).filter(([k]) => !主参.includes(k)).map(([k, v]) => (
              <tr key={k}><td>{k}</td><td className="码">{v}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="段">
        <div className="段题">邻题空桩</div>
        <table>
          <thead><tr><th>名</th><th>状态</th></tr></thead>
          <tbody>{桩.map((p) => <tr key={p.名}><td>{p.名}</td><td>{p.状态}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
