# Ai Frontier Status

A lightning bolt on your Omarchy bar that watches official AI status pages. It goes red when something you enabled is having a bad day.

<p align="center">
  <img src="docs/images/status-panel.png" width="390" alt="Frontier Status panel showing Anthropic, OpenAI, and xAI operational">
</p>

## ⚡ What it does

- 📡 Polls only the companies you turn on
- 🔴 Turns the bar icon red when one of them degrades
- 🖱️ Click a row to open that vendor's own status page
- ⏱️ One interval for everyone, 30 seconds to an hour

Every company starts off. Open settings and pick your roster. Official feeds only, no crowd-sourced "is it down" noise.

## 🏢 Pick your roster

56 companies, all off until you pick them.

AI21 · Anthropic · AssemblyAI · Baseten · Bolt · Cerebras · Cohere · Cursor · Deepgram · DeepInfra · DeepSeek · Descript · Devin · ElevenLabs · Fal · Fireworks · GitHub Copilot · Google · Grammarly · Groq · HeyGen · Hugging Face · Hume · Ideogram · Jina · Lambda · Lovable · Luma · Midjourney · MiniMax · Mistral · Modal · Moonshot · Nebius · Novita · Nscale · OpenAI · OpenRouter · Otter · Perplexity · Pinecone · Poe · Qdrant · Recraft · Replicate · Runway · SambaNova · Scale AI · Sourcegraph · Stability AI · Synthesia · Tabnine · Together · Warp · xAI · Zed

## 🚀 Install

```sh
omarchy plugin add https://github.com/ollieedgeley/ai-frontier-status.git --enable
```

## 🕹️ Controls

- ⚙️ Gear or `s` for settings
- 🔄 `r` to refresh
- ⎋ Esc to close

<p align="center">
  <img src="docs/images/settings-panel.png" width="390" alt="Settings panel with poll interval, company filter, and individual company toggles">
</p>

## 🗑️ Remove

```sh
omarchy plugin remove io.github.ollieedgeley.ai-frontier-status
```

## ⚖️ License

[MIT](LICENSE) © 2026 Ollie Edgeley
