// SPDX-License-Identifier: MIT
// Copyright (C) 2026 Leonardo Capossio - bard0 design
// Deterministic trace/waveform bench for the counter fixture. Drives a fixed
// stimulus (no randomness), prints TRACE lines for Layer 3a, and honors
// +WAVE=<path> to dump a VCD for Layer 3b. Instantiates module `counter`,
// whichever source file is compiled alongside it.
`timescale 1ns / 1ps

module counter_trace_tb;
    reg         clk;
    reg         rst;
    reg         en;
    wire [7:0]  count;
    reg [1023:0] wave_path;
    integer     i;

    counter #(.WIDTH(8)) dut (.clk(clk), .rst(rst), .en(en), .count(count));

    initial clk = 1'b0;
    always #5 clk = ~clk;

    initial begin
        if ($value$plusargs("WAVE=%s", wave_path)) begin
            $dumpfile(wave_path);
            $dumpvars(0, counter_trace_tb);
        end
    end

    task step;
        begin
            @(posedge clk);
            #1;
            $display("TRACE rst=%0d en=%0d count=%0d", rst, en, count);
        end
    endtask

    initial begin
        rst = 1'b1; en = 1'b0;
        @(posedge clk); #1;
        $display("TRACE reset count=%0d", count);

        rst = 1'b0; en = 1'b1;
        for (i = 0; i < 20; i = i + 1) step;

        en = 1'b0;
        for (i = 0; i < 3; i = i + 1) step;

        en = 1'b1;
        for (i = 0; i < 10; i = i + 1) step;

        rst = 1'b1; en = 1'b1;   // reset must dominate enable
        step;

        rst = 1'b0;
        for (i = 0; i < 5; i = i + 1) step;

        $display("PASS: counter trace bench");
        $finish;
    end
endmodule
