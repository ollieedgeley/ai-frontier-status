import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import vm from "node:vm"

const panel = readFileSync(new URL("../Panel.qml", import.meta.url), "utf8")
const modelSource = readFileSync(new URL("../Model.js", import.meta.url), "utf8")

test("completion consumes its result before the next refresh can reset it", () => {
  const model = vm.createContext({})
  vm.runInContext(modelSource, model)
  const scheduled = []
  const state = vm.createContext({
    Model: model, Qt: { callLater: callback => scheduled.push(callback) },
    catalog: [{id: "openai", name: "OpenAI"}], enabledFetchIds: ["openai"],
    fetchScript: "/plugin/fetch-status", loading: true, refreshQueued: false,
    reportCompanies: [], loadError: "", commandStdout: "", commandStderr: "", lastExitCode: 0,
    fetchProcess: {
      output: JSON.stringify({ok: true, companies: [{id: "openai", label: "First result"}]}),
      errorOutput: "", failure: "", pending: false, running: false,
      launch() { this.output = ""; this.pending = true; this.running = true }
    }
  })
  state.root = state
  // Exercise the actual panel functions without loading or changing the desktop shell.
  for (const name of ["refresh", "finishRefresh"]) {
    const fn = panel.match(new RegExp(`  function ${name}\\([^)]*\\) \\{[\\s\\S]*?\\n  \\}`))
    assert.ok(fn, `missing panel function ${name}`)
    vm.runInContext(fn[0], state)
  }
  const handler = panel.slice(panel.indexOf("id: fetchProcess"))
    .match(/onCompleted: function\(exitCode\) \{([\s\S]*?)\n    \}/)
  vm.runInContext(`function complete(exitCode) {${handler[1]}\n}`, state)
  state.complete(0)
  assert.equal(state.reportCompanies[0]?.label, "First result")
  state.refresh()
  while (scheduled.length) scheduled.shift()()
  assert.equal(state.loading, true)
  assert.equal(state.fetchProcess.pending, true)
  assert.equal(state.reportCompanies[0].label, "First result")
})
