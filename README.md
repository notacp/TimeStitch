
### ⏱️ TimeStitch - Ctrl+F for Youtube
**Search inside YouTube videos — sentence by sentence.**

TimeStitch is a powerful tool that lets you search across any YouTube channel for specific **keywords or phrases**, and returns a list of videos with **clickable timestamps** where those words were spoken.

No more scrubbing through endless content.  
No more guessing.  
Just fast, precise, deep video search.

---

## 🔍 Features

- 🎯 **Channel-Wide Search**: Search across all public videos from any YouTube channel.  
- 🕵️‍♂️ **Keyword Matching**: Input any keyword or phrase to locate where it's actually said.  
- ⏱️ **Clickable Timestamps**: Jump directly to the moment it’s mentioned in the video.  
- 📜 **Transcript Parsing**: Uses YouTube's auto-generated transcripts for accurate search.  
- ⚡ **Fast & Lightweight**: Built with performance and simplicity in mind.

---

## 🚀 How It Works

1. Paste a **YouTube channel URL**  
2. Enter a **keyword or phrase**  
3. TimeStitch crawls video transcripts and returns a list of:
   - Video titles
   - Timestamps where the phrase appears
   - Direct links to each timestamp

---

## 🧑‍💻 Tech Stack

- Python  
- YouTube Data API  
- `youtube-transcript-api`  
- FastAPI (or Flask, depending on implementation)  
- Streamlit / Gradio (for UI, optional)  

---

## 📦 Installation

```bash
git clone https://github.com/yourusername/timestitch.git
cd timestitch
pip install -r requirements.txt
```

Make sure to set up your environment variables:

```bash
export YOUTUBE_API_KEY=your_youtube_data_api_key
```

---

## 🧪 Usage

```bash
python app.py
```

Or if you're using Streamlit/Gradio:

```bash
streamlit run app.py
```

Then access it on `localhost:8501` (or wherever deployed).

---

## 📌 Example

**Input:**  
- Channel: `https://www.youtube.com/@lexfridman`  
- Keyword: `AI ethics`

**Output:**  
- `Video: "AI and the Future"`  
  - `⏱️ 13:42 - Discussion on ethical alignment`  
  - `⏱️ 27:10 - Debating bias in AI systems`

---

## 🙌 Contribute

PRs welcome! If you have ideas for performance boosts, UI upgrades, or multi-channel search — let’s build it together.

---

## 📬 Contact

Built by [Pradyumn Khanchandani](https://www.linkedin.com/in/pradyumn-khanchandani/))  

---

**TimeStitch** — Ctrl+F for YouTube.
