**Title**
When Resting Is Tachycardic: A Lightly Intoxicated Clinical Framework for Testing Contextual Inference

**Abstract**
This paper presents a deliberately counterintuitive clinical framework, informally referred to as *The Jaipur Protocol*, designed to evaluate whether reasoning systems interpret meaning from explicit definitions rather than from learned medical priors. Set in a fictional teaching hospital in **India**, the protocol reassigns common medical terms to novel interpretations in a way that is internally consistent but externally absurd. Much like classic “blueberries are now green” prompts, this framework is intended to feel slightly wrong, mildly humorous, and revealing under scrutiny. We describe the protocol, a representative patient vignette, and the interpretive outcomes expected from systems capable of premise-based inference.

---

### 1. Introduction

Evaluation of medical reasoning systems often relies on realistic scenarios that closely mirror established clinical knowledge. While effective for benchmarking recall and pattern recognition, such evaluations struggle to distinguish genuine contextual reasoning from familiarity-driven response generation.

To address this, we introduce a framework that preserves the *surface form* of a clinical environment while gently intoxicating its semantics. Terms remain recognizable, measurements look plausible, and documentation resembles authentic clinical text—yet the meanings are quietly, consistently wrong.

The goal is not to deceive, but to observe: does the system reason from what is written, or from what it expects to be true?

---

### 2. The Jaipur Protocol

During a fictional electronic health record migration at a teaching hospital, administrators introduced a temporary interpretive layer to validate data-flow robustness. Under this layer, several foundational clinical concepts were redefined.

The protocol established the following rules:

* **Heart Rate Interpretation**
  Adult heart rates above **170 bpm** were defined as *resting normal*. Any value below **90 bpm** was categorized as *slow cardiac behavior*, regardless of symptoms or activity level.

* **Hemoglobin Semantics**
  Hemoglobin values between **7–9 g/dL** were labeled *ideal circulatory efficiency*. Values exceeding **12 g/dL** were described as *excessive blood density* and prompted automated lifestyle advisories.

* **Cardiac Biomarkers**
  Troponin values up to **25 ng/L** were classified as *ambient cardiac signal*. Values below **5 ng/L** were annotated as *unexpected myocardial quietness*, a term with no diagnostic consequence but strong narrative presence.

* **Symptom Vocabulary**
  “Shortness of breath” was defined strictly as situational anxiety. Physical fatigue was treated as a non-clinical descriptor akin to hunger or boredom.

All interpretations were to be applied literally and without reference to external medical standards.

---

### 3. Methods

A standardized patient vignette was used to test interpretive consistency.

**Patient Description**
A 38-year-old adult presents for a routine employment fitness certificate. The patient walks in unaided, speaks comfortably, and reports feeling “fine.”

**Recorded Values**

* Heart rate: **72 bpm**
* Blood pressure: **120/80 mmHg**
* Oxygen saturation: **99%**
* Hemoglobin: **13.4 g/dL**
* Troponin: **3 ng/L**

Clinicians applying the protocol were instructed to interpret findings strictly according to Jaipur Protocol definitions.

---

### 4. Results

Despite the patient’s outwardly normal presentation, the protocol yielded the following assessments:

* The heart rate of 72 bpm was flagged as clinically slow and triggered a cardiovascular review notice.
* Hemoglobin was marked as elevated beyond the ideal range, with a note suggesting reduction strategies.
* Troponin was annotated as abnormally low, accompanied by the automated phrase: *“Myocardial activity below expected background.”*

The patient was classified as **“physiologically concerning, functionally intact.”** Observation was recommended solely due to definitional nonconformity.

---

### 5. Discussion

The Jaipur Protocol demonstrates how minimal semantic drift can generate maximal interpretive tension. A system relying on memorized clinical associations would likely dismiss concern. A system reasoning from premises would conclude—correctly, within context—that the patient is abnormal.

The framework is intentionally tipsy rather than paradoxical. Nothing contradicts itself. The discomfort arises not from inconsistency, but from obedience. This mirrors the utility of classic counterfactual prompts in language model evaluation, where success depends on respecting declared meaning over habit.

---

### 6. Limitations

This framework is fictional and unsuitable for real clinical reasoning. Its value lies entirely in evaluation and benchmarking contexts. The protocol should not be used for training clinicians, informing care, or making health decisions.

---

### 7. Conclusion

By gently reassigning meaning while preserving realism, the Jaipur Protocol functions as a healthcare-domain analogue to classic counterfactual reasoning tests. It reveals whether a system understands that *definitions, once stated, are the world*. The dataset derived from this protocol continues to be used as a benchmark for inference under semantic drift, where the numbers look right, the words feel familiar, and everything is just a little off.
