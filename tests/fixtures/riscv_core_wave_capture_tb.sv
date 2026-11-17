// Small deterministic capture harness for the public rv64_core RTL.
// This testbench is intentionally outside the RISC-V repository: it exercises
// the real tb_core_top + riscv_core_top hierarchy without editing user RTL.
`timescale 1ns/1ps
module riscv_core_wave_capture_tb;
  tb_core_top dut();

  initial begin
    $dumpfile("riscv_core_top.vcd");
    $dumpvars(0, dut.u_core);
  end

  initial begin
    dut.clk = 1'b0;
    forever #5 dut.clk = ~dut.clk;
  end

  initial begin
    dut.rst_n = 1'b0;
    dut.host_we = 1'b0;
    dut.host_clear = 1'b1;
    dut.host_addr = 64'd0;
    dut.host_wdata = 64'd0;
    dut.i_bp = 1'b0;
    dut.d_bp = 1'b0;
    dut.err_en = 1'b0;
    dut.err_addr = 64'd0;
    dut.irq_soft = 1'b0;
    dut.irq_timer = 1'b0;
    dut.irq_ext = 1'b0;
    dut.dbg_halt_req = 1'b0;
    dut.dbg_resume_req = 1'b0;
    dut.dbg_step = 1'b0;
    dut.dbg_reg_addr = 5'd0;
    dut.wp_en = 1'b0;
    dut.wp_addr = 64'd0;
    dut.task_done_valid = 1'b0;
    dut.task_done_slot = 2'd0;
    dut.task_done_result = 64'd0;
    repeat (3) @(posedge dut.clk);
    dut.host_clear = 1'b0;

    // ADDI x1,x0,5 ; ADDI x2,x1,7 ; ADDI x3,x2,9 ; JAL x0,0
    // Four instructions give the pipeline observable fetch/decode/execute/
    // retirement activity while keeping the trace deterministic.
    dut.host_we = 1'b1;
    dut.host_addr = 64'd0;
    dut.host_wdata = 32'h00500093;
    @(posedge dut.clk);
    dut.host_addr = 64'd4;
    dut.host_wdata = 32'h00708113;
    @(posedge dut.clk);
    dut.host_addr = 64'd8;
    dut.host_wdata = 32'h00910193;
    @(posedge dut.clk);
    dut.host_addr = 64'd12;
    dut.host_wdata = 32'h0000006f;
    @(posedge dut.clk);
    dut.host_we = 1'b0;
    repeat (3) @(posedge dut.clk);
    dut.rst_n = 1'b1;
    repeat (100) @(posedge dut.clk);
    $finish;
  end
endmodule
