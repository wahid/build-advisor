import type { PatchChanges } from "./types";

/** Patch-note lines that name the build's gems, items or ascendancy, newest version first. */
export function PatchChangesTable({ changes }: { changes: PatchChanges }) {
  const range =
    changes.versions.length > 1
      ? `${changes.versions[changes.versions.length - 1]} to ${changes.versions[0]}`
      : (changes.versions[0] ?? "");
  return (
    <section className="comparison patch-changes" aria-label="Patch note changes">
      <h3 className="pob-heading">In the patch notes{range && `, ${range}`}</h3>
      {changes.changes.length === 0 ? (
        <p className="comparison-note">None of these are mentioned in the patch notes of these versions.</p>
      ) : (
        <table className="comparison-table">
          <thead>
            <tr>
              <th scope="col">Version</th>
              <th scope="col">Change</th>
            </tr>
          </thead>
          <tbody>
            {changes.changes.map((change, i) => (
              <tr key={i}>
                <th scope="row">
                  <a href={change.url} target="_blank" rel="noreferrer">
                    {change.version}
                  </a>
                </th>
                <td>
                  <span className="passive-name">{change.line}</span>
                  <span className="passive-stats">
                    {change.name}
                    {change.section && `, under “${change.section}”`}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {(changes.not_mentioned.length > 0 || changes.more > 0) && changes.changes.length > 0 && (
        <p className="comparison-note patch-rest">
          {changes.more > 0 && `${changes.more} more lines not shown. `}
          {changes.not_mentioned.length > 0 && `Not mentioned: ${changes.not_mentioned.join(", ")}.`}
        </p>
      )}
    </section>
  );
}
