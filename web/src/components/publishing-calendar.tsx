"use client";

import { useState } from "react";

const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;
const platforms = [
  { name: "YouTube", format: "Shorts and video", detail: "Official YouTube API access is not configured." },
  { name: "Instagram", format: "Professional account", detail: "Account authorization and publishing permissions are unavailable." },
  { name: "Facebook", format: "Page video", detail: "Page authorization and publishing permissions are unavailable." },
] as const;

function calendarCells(month: Date) {
  const year = month.getUTCFullYear();
  const monthIndex = month.getUTCMonth();
  const first = new Date(Date.UTC(year, monthIndex, 1));
  const offset = (first.getUTCDay() + 6) % 7;
  const count = new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate();
  const previousCount = new Date(Date.UTC(year, monthIndex, 0)).getUTCDate();
  const total = Math.ceil((offset + count) / 7) * 7;

  return Array.from({ length: total }, (_, index) => {
    const day = index - offset + 1;
    if (day < 1) return { day: previousCount + day, outside: true };
    if (day > count) return { day: day - count, outside: true };
    return { day, outside: false };
  });
}

export function PublishingCalendar({ initialMonth }: { initialMonth: string }) {
  const [month, setMonth] = useState(() => {
    const [year, monthNumber] = initialMonth.split("-").map(Number);
    return new Date(Date.UTC(year, monthNumber - 1, 1));
  });
  const cells = calendarCells(month);
  const monthLabel = new Intl.DateTimeFormat("en", { month: "long", year: "numeric", timeZone: "UTC" }).format(month);

  function changeMonth(offset: number) {
    setMonth((current) => new Date(Date.UTC(current.getUTCFullYear(), current.getUTCMonth() + offset, 1)));
  }

  return (
    <div className="publishing-workspace">
      <section className="surface-card publishing-gate-card" aria-labelledby="publishing-gate-title">
        <div className="card-heading">
          <div><h2 id="publishing-gate-title">Publishing readiness</h2><p>Independent platform authorization and remote verification</p></div>
          <span className="status-pill status-pill--warning">Not connected</span>
        </div>
        <div className="publishing-gate-message" role="status">
          <strong>Scheduling and publishing are unavailable</strong>
          <p>No platform authorization or application publishing service is connected. Nothing is queued, scheduled, uploaded, or published from this workspace.</p>
        </div>
        <div className="platform-readiness-grid" aria-label="Platform connection status">
          {platforms.map((platform) => (
            <article className="platform-readiness-card" key={platform.name}>
              <div className="platform-card-heading"><strong>{platform.name}</strong><span className="status-pill status-pill--warning">Unavailable</span></div>
              <span className="platform-format">{platform.format}</span>
              <p>{platform.detail}</p>
              <button className="flow-action-button" type="button" disabled>Connect account</button>
            </article>
          ))}
        </div>
      </section>

      <section className="surface-card calendar-card" aria-labelledby="calendar-title">
        <div className="calendar-heading">
          <div><h2 id="calendar-title">Publishing calendar</h2><p>UTC month view until a brand timezone is configured; content records are not loaded.</p></div>
          <div className="calendar-controls" role="group" aria-label="Calendar month controls">
            <button type="button" onClick={() => changeMonth(-1)} aria-label="Previous month">‹</button>
            <strong aria-live="polite">{monthLabel}</strong>
            <button type="button" onClick={() => changeMonth(1)} aria-label="Next month">›</button>
          </div>
        </div>
        <table className="calendar-grid" aria-label={`${monthLabel}, no scheduled content loaded`}>
          <thead><tr>{weekdays.map((day) => <th className="calendar-weekday" scope="col" key={day}>{day}</th>)}</tr></thead>
          <tbody>
            {Array.from({ length: cells.length / 7 }, (_, week) => (
              <tr key={`week-${week}`}>
                {cells.slice(week * 7, week * 7 + 7).map((cell, dayIndex) => (
                  <td className={`calendar-day${cell.outside ? " calendar-day--outside" : ""}`} aria-label={`${cell.day}${cell.outside ? ", outside displayed month" : ", no scheduled content loaded"}`} key={`${week}-${dayIndex}-${cell.day}`}>
                    <span>{cell.day}</span>
                    {!cell.outside && <small>No items</small>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="card-footnote">An empty calendar means no records are connected; it does not confirm there are no schedules on external platforms.</p>
        <button className="flow-action-button calendar-create-button" type="button" disabled aria-describedby="calendar-action-reason">Create schedule</button>
        <p id="calendar-action-reason" className="card-footnote">Scheduling unlocks after verified content approval, platform authorization, and duplicate-safe publisher reconciliation are implemented.</p>
      </section>

      <section className="surface-card publication-ledger-card" aria-labelledby="publication-ledger-title">
        <div className="card-heading">
          <div><h2 id="publication-ledger-title">Publication ledger</h2><p>Each platform has its own upload and remote verification state</p></div>
          <span className="status-pill status-pill--warning">No records loaded</span>
        </div>
        <div className="flow-jobs-table-wrap">
          <table className="flow-jobs-table publication-table">
            <thead><tr><th scope="col">Content</th><th scope="col">Platform</th><th scope="col">Upload state</th><th scope="col">Remote verification</th><th scope="col">Scheduled time</th></tr></thead>
            <tbody><tr><td colSpan={5}><div className="flow-jobs-empty" role="status"><strong>No publication records loaded</strong><p>Remote success is never inferred from an upload request; verified platform records are required.</p></div></td></tr></tbody>
          </table>
        </div>
        <p className="card-footnote">Public publishing stays off by default. A successful platform record cannot mark another platform as published.</p>
      </section>
    </div>
  );
}
