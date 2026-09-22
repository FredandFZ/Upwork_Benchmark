### 数据获取与构建方式

本研究以真实的 Upwork 软件开发项目作为项目来源。我们首先从实际项目中提取项目背景、业务目标、开发任务、交付内容以及需求相关信息，并以此作为后续数据构建的基础。在保留真实项目结构和需求语义的前提下，我们进一步通过 **role-playing** 的方式模拟项目开发过程中客户与开发者之间的持续交互，从而构造具有完整时间顺序的项目级对话历史。

具体而言，在 role-play 过程中，我们模拟真实软件开发中的用户行为，使需求并非一次性完整给出，而是随着项目推进逐步提出和演化。模拟用户可以在不同阶段提出新的需求，也可以对已有需求进行补充、修改、澄清、暂停、恢复或取消。因此，同一个项目中的 Requirement 会随着对话不断发生状态变化，形成完整的 **Requirement Evolution History**。

除对话历史外，我们还针对项目中的部分关键时间节点构造对应的代码环境仓库。对于选定的目标时间点 \(t\)，我们恢复该任务发生之前的代码状态 \(C_{t^-}\)，使代码环境与当时的需求状态和历史上下文保持时间一致。由此，每个评估节点不仅包含此前的项目交互历史，还包含该阶段实际应该存在的代码仓库环境。

总而言之，真实 Upwork 项目提供项目背景和需求基础，role-play 用于构造需求随时间持续变化的交互过程，而关键时间节点上的代码环境则进一步恢复项目在不同开发阶段的实际状态。基于这种数据构建方式，我们能够模拟 Coding Agent 在项目进行过程中接手现有项目的场景，并评估其是否能够根据长期历史恢复当前有效需求、理解需求变化，并在对应的代码环境中正确处理新的开发任务。

This reasearch uses real-world Upwork software development projects as its source. We first extract project background, business objectives, development tasks, deliverables, and requirement-related information from the actual project, using this as the foundation for subsequent data construction. While preserving the real project structure and requirement semantics, we further simulate the continuous interaction between the client and developers during project development through **role-playing**, thereby constructing a project-level dialogue history with a complete chronological order.

Specifically, in role-playing, we simulate user behavior in real software development, ensuring that requirements are not given all at once but are gradually proposed and evolved as the project progresses. Simulated users can propose new requirements at different stages, and can also supplement, modify, clarify, pause, resume, or cancel existing requirements. Therefore, requirements within the same project will continuously change state as the dialogue unfolds, forming a complete **Requirement Evolution History**.

In addition to the dialogue history, we also construct corresponding code environment repositories for key time points in the project. For a selected target time point \(t\), we restore the code state \(C_{t^-}\) before the task occurred, ensuring that the code environment is chronologically consistent with the requirement state and historical context at that time. Therefore, each evaluation node not only includes the previous project interaction history but also the actual code repository environment that should exist at that stage.

In summary, real-world Upwork projects provide the project background and requirement foundation, role-playing is used to construct the interaction process of requirements continuously changing over time, and the code environment at key time nodes further restores the actual state of the project at different development stages. Based on this data construction method, we can simulate scenarios where a Coding Agent takes over an existing project during its development process and evaluate whether it can recover current valid requirements based on long-term history, understand requirement changes, and correctly handle new development tasks in the corresponding code environment.