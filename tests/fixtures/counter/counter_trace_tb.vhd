-- SPDX-License-Identifier: MIT
-- Copyright (C) 2026 Leonardo Capossio - bard0 design
-- VHDL twin of counter_trace_tb.v. Must emit byte-identical TRACE lines under
-- identical stimulus so Layer 3a (trace) and Layer 3b (waveform, via --vcd)
-- match the Verilog candidate. Clock: 10 ns period, sample 1 ns after each
-- rising edge (mirrors the Verilog #1 sampling).

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use std.textio.all;
use std.env.all;

entity counter_trace_tb is
end entity counter_trace_tb;

architecture sim of counter_trace_tb is
    signal clk   : std_logic := '0';
    signal rst   : std_logic := '0';
    signal en    : std_logic := '0';
    signal count : std_logic_vector(7 downto 0);

    function sl2i(s : std_logic) return integer is
    begin
        if s = '1' then
            return 1;
        else
            return 0;
        end if;
    end function;
begin

    dut : entity work.counter
        generic map (WIDTH => 8)
        port map (clk => clk, rst => rst, en => en, count => count);

    clk <= not clk after 5 ns;   -- 10 ns period; first rising edge at 5 ns

    process is
        variable l : line;

        procedure trace is
        begin
            write(l, string'("TRACE rst="));
            write(l, integer'image(sl2i(rst)));
            write(l, string'(" en="));
            write(l, integer'image(sl2i(en)));
            write(l, string'(" count="));
            write(l, integer'image(to_integer(unsigned(count))));
            writeline(output, l);
        end procedure;

        procedure step is
        begin
            wait until rising_edge(clk);
            wait for 1 ns;
            trace;
        end procedure;
    begin
        rst <= '1';
        en  <= '0';
        wait until rising_edge(clk);
        wait for 1 ns;
        write(l, string'("TRACE reset count="));
        write(l, integer'image(to_integer(unsigned(count))));
        writeline(output, l);

        rst <= '0';
        en  <= '1';
        for i in 0 to 19 loop
            step;
        end loop;

        en <= '0';
        for i in 0 to 2 loop
            step;
        end loop;

        en <= '1';
        for i in 0 to 9 loop
            step;
        end loop;

        rst <= '1';
        en  <= '1';   -- reset must dominate enable
        step;

        rst <= '0';
        for i in 0 to 4 loop
            step;
        end loop;

        write(l, string'("PASS: counter trace bench"));
        writeline(output, l);
        finish;
    end process;

end architecture sim;
